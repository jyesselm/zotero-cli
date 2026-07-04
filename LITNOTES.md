# Literature Notes — standard + build runbook

How to turn Zotero PDFs into standardized Obsidian literature notes (text + real figures +
agent-written summary + tag-MOCs), and **do it the same way every time**. Vault: `~/notes`.

> **Golden rules**
> - **Note reads/writes/frontmatter go through the Obsidian MCP** (`mcp__obsidian__*`) — it
>   respects the vault, serializes frontmatter cleanly, and is the supported path. Do **not**
>   hand-write note files.
> - **Figures (binary) are copied to the vault with the filesystem** — the MCP is note-only.
> - **Zotero is read-only** for this whole flow (metadata, `pdf_path`, annotations). No DB writes.
> - **CREATE-only**: if a note already exists for a paper, **SKIP + report** — never clobber a
>   hand-written note.

---

## 1. The standard header (frontmatter)

Every literature note carries exactly these keys, in this order. Ownership = who may edit.

| key | owner | purpose | example |
|---|---|---|---|
| `title` | machine | paper title | `Computational design of three-dimensional RNA…` |
| `authors` | machine | full author list (Dataview-queryable) | `[Joseph D. Yesselman, …, Rhiju Das]` |
| `year` | machine | publication year | `2019` |
| `journal` | machine | venue | `Nature Nanotechnology` |
| `doi` | machine | DOI | `10.1038/s41565-019-0517-8` |
| `url` | machine | publisher link | `https://…` |
| `citekey` | machine | Author+Year | `Yesselman2019` |
| `zotero_key` | machine | **stable identity** for re-matching / round-trip | `PAXAQR7U` |
| `zotero` | machine | deep link | `zotero://select/library/items/PAXAQR7U` |
| `type` | machine | note class (vault convention) | `literature` |
| `tags` | machine | Obsidian-level note tag | `[literature]` |
| `paper-tags` | machine | **controlled vocabulary** (drives MOCs/Dataview); leaf tags | `[method/dms, topic/…, status/key-paper]` |
| `status` | **human** | reading state | `unread` \| `reading` \| `read` |
| `date` | machine (once) | added to vault | `2026-07-04` |
| `updated` | **human** | last human edit | `2026-07-04` |
| `zot_built` | machine | last regeneration date (provenance) | `2026-07-04` |
| `zot_pipeline` | machine | extractor version (re-run detection) | `1` |
| `figures` | machine | figure count (dashboards) | `4` |
| `has_fulltext` | machine | full-text sibling exists | `true` |

Rules: controlled tags go in **`paper-tags`** (not `tags`) and are **leaf-only** (`method/dms`, not also
`method/chemical-mapping`). MOCs/Dataview query `paper-tags`. `status` and `updated` are human-owned;
regeneration must preserve them.

## 2. Locations & naming (fixed conventions)

- **Note:** `300-reference/science/<slug>.md`
- **Slug:** `firstauthor-year-shorttitle`, lowercase-hyphen (e.g. `yesselman-2019-computational-3d-rna-design`; matches the vault's `homan-2014-ring-mapper`). Add `-b`,`-c` on collision.
- **Reading note (full text):** `300-reference/science/<slug>.fulltext.md` — a **paper-like reconstruction**:
  `#`/`###` section headings (font/bold-detected), **figures embedded inline** at their caption positions,
  cleaned prose. Linked from the dashboard note (not transcluded). Written to the filesystem (large).
- **Figures:** `300-reference/science/attachments/<slug>/figN.png`.
- **MOCs:** `300-reference/science/MOCs/MOC - <tag-slug>.md` (tag `/` → `-`).
- **Zotero URIs:** `zotero://select/library/items/<KEY>` and `zotero://open-pdf/library/items/<KEY>`
  (the format the vault's own notes use — **not** `select/items/0_<KEY>`).

## 3. Body structure (managed regions)

Machine-owned content lives between markers; **everything else is human-owned and never touched**:

```
# {title}
**{first} … {last}** · {year} · *{journal}* · [DOI](…)
## Links   (Zotero select · open-pdf · full-text link)
<!-- zot:auto:start:moc -->    ## MOCs → [[MOC - <tag>]] …            <!-- zot:auto:end:moc -->
## Summary
<!-- zot:auto:start:summary --> (agent: TL;DR / contributions / methods / limitations) <!-- zot:auto:end:summary -->
<!-- zot:auto:start:figures --> ## Figures → ![[attachments/<slug>/figN.png]] + "> Fig N. caption" <!-- zot:auto:end:figures -->
<!-- zot:auto:start:text -->    ## Extracted text → link to [[<slug>.fulltext]]  <!-- zot:auto:end:text -->
## Notes / ## Key Points / ## Questions   ← HUMAN-OWNED
```

## 4. Build runbook (repeat this)

1. **Pick the subset.** e.g. `zot search -t status/key-paper` → item IDs + `pdf_path`.
2. **Extract** (deterministic, read-only): run the extractor (`extract_lit.py`) on the PDFs →
   per paper: `figs/*.png`, `bundle.json` (figures+full captions+tier), `references.txt`, `text.txt`.
   - Figures use caption-anchored **graphics-union** rendering (raster + vector), nearest-caption
     assignment, validate-before-emit; caption-only when no real graphics (never a fake image).
   - **Text is cleaned** (`clean.py`), never raw `get_text()`: column-aware reading order (fixes
     title/authors landing mid-text), smart **de-hyphenation** (keeps real compounds like
     `single-chain` via a per-doc compound set; merges soft breaks like `algo-rithm`), paragraph
     reflow, ligature normalization (`ﬁ`→`fi`), and removal of page furniture (running heads,
     page numbers), figure-internal text (panel labels, axis numbers), and the trailing reference
     list. References are captured separately in `references.txt`.
3. **Per paper:**
   a. **Existence check** via MCP (`search_notes` / `get_frontmatter`) by `zotero_key` then `doi`
      across `300-reference/science/` **and** `…/papers/`. If found → **SKIP + report**, don't write.
   b. **Copy figures** to `attachments/<slug>/` (filesystem `cp`).
   c. **Write the full-text sibling** `<slug>.fulltext.md`.
   d. **Agent writes the executive summary** from `bundle.json` (`sections` + captions; use Zotero
      annotation highlights as seeds *only if the item has any*).
   e. **Write the main note** with `mcp__obsidian__write_note` — pass the standard header as the
      `frontmatter` object and the body (with managed regions) as `content`.
4. **MOCs:** `moc-sync` builds `MOC - <tag>` for **method/system/topic/type** tags + a floor
   `MOC - key-papers` (so every note links ≥1 MOC). Each MOC = a Dataview query
   (`TABLE year, journal FROM "300-reference/science" WHERE contains(paper-tags,"<tag>")`) **plus** a
   marker-fenced static wikilink list. Deny `status/*` (except floor), `cited/*`, `lab/*`, `type/my-paper`.
5. **Verify** in Obsidian: figures render, captions present, MOC + Zotero links resolve, human
   sections intact.

## 5. Invariants (do not violate)

- Obsidian MCP for all note ops; figures via filesystem; Zotero read-only.
- Emit a figure embed **only after** the PNG exists (no broken embeds).
- Regeneration rewrites **only** inside `zot:auto` fences; preserves `status`/`updated`/`science-tags`
  and all human sections; CREATE-only (SKIP existing notes).
- Full text is **linked**, not transcluded (bodies run 50k–130k chars).
- **Extracted text is markdown-escaped** against a fixed register before it's written into a note:
  escape `* _ \` ~ < > [ ]` and leading `# > | + -`. Without this, stray PDF characters (e.g. the
  corresponding-author `*`) open unclosed emphasis and corrupt the whole note's rendering. Only the
  markdown the builder *adds* (headings `##`, bold `**Fig N |**`, embeds `![[…]]`) is left unescaped.
- **Table cell-text is dropped** (fragment lines after a `Table N` caption) and **figure/axis text**
  excluded (blocks inside figure regions), so neither leaks into the prose.

## 6. Reference implementation

`300-reference/science/yesselman-2019-computational-3d-rna-design.md` (+ its `.fulltext.md` and
`attachments/…/fig1-4.png`) is the canonical example — copy its shape.
