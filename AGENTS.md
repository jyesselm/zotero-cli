# AGENTS.md — using `zot` (Zotero CLI) safely

Guide for AI agents operating this repo's `zot` CLI against a **live, sync-enabled Zotero
library**. Read the safety rules before any write.

`zot` reads and writes Zotero's SQLite DB directly (no running Zotero/API needed). Entry point:
`zot` (installed) or `python -m zotero_cli.cli`.

---

## 🛑 Safety rules (read first)

1. **Writes require Zotero to be CLOSED.** A running Zotero locks the DB and a concurrent write
   can corrupt it. Check first: `pgrep -fi zotero` (the macOS process is lowercase `zotero`, so
   `pgrep -x Zotero` misses it). The write commands (`new-collection`, `new-project`, `deltag`,
   …) self-guard and refuse if Zotero is open; ad-hoc SQL scripts must check themselves. **Reads
   are always safe** — they run against a temp copy of the DB.
2. **Back up before any batch write:** `cp ~/Zotero/zotero.sqlite ~/Zotero/zotero.sqlite.bak-$(date +%Y%m%d-%H%M%S)`.
   Restore = copy a backup back (Zotero closed). Storage folders live at `~/Zotero/storage/`.
3. **Item/collection keys use a restricted alphabet** `23456789ABCDEFGHIJKLMNPQRSTUVWXYZ`
   (no `0`,`1`,`O`, no lowercase). Using anything else makes Zotero's sync reject the whole
   library ("`X` is not a valid item key"). `_generate_key()` already does this — use it, never
   hand-roll keys.
4. **Sync only propagates "dirty" objects.** Zotero uploads an object only if it's marked
   `synced=0` (new objects also `version=0`). Raw tag/collection edits that don't set `synced=0`
   on the changed row **won't reach other computers** (or the server may resurrect a deleted
   object). New items/collections created by `zot` set `version=0, synced=0` correctly. If you
   edit rows by hand, mark them dirty. Deletions must also be logged (`syncDeleteLog`) — prefer
   deleting collections/items in the **Zotero GUI**, which logs correctly.
5. **After writes, the user must open Zotero to sync.** `zot` cannot perform the network sync.

---

## Command reference

Read-only (safe anytime):
- `zot search <query> [-a author] [-t tag] [-c collection] [-y year] [--type T] [-n N]`
- `zot list [-n N] [-u/--untagged]` · `zot recent [-n N]` · `zot incomplete [-n N]`
- `zot show <id>` · `zot abstract <id>` · `zot path <id>` · `zot cite <id> [-f inline|bibtex|apa]`
- `zot tags [--tree]` · `zot collections [--tree]`
- `zot duplicates` · `zot check <pdf>` (is this PDF's DOI already in the library?)
- `zot suggest <id>` / `zot suggest-all` (keyword tag suggestions — see vocabulary below)
- `zot i [query]` (interactive fzf browser; needs a TTY — not for headless agents)

Writes (Zotero must be closed):
- **Papers:** `zot add <pdf> [--trash|--delete]` · `zot scan <dir> [-r] [--keep] [--dry-run]`
  (extract DOI → CrossRef/PubMed metadata → dedup by DOI/title → add; `scan` trashes originals
  unless `--keep`). `zot fix <id> [--dry-run]` fills missing metadata from CrossRef.
- **Tags:** `zot tag <id> <name>` · `zot untag <id> <name>` · `zot retag <old> <new>`
  (rename/merge) · `zot deltag <name>` (remove globally) · `zot tag-collection <coll> <name>`.
- **Collections:** `zot new-collection <name> [-p parent]` · `zot new-project <name>`
  (creates `Projects/<name>` + a colored `cited/<name>` tag).
- **Dedup:** `zot dedup [--apply]` (default dry-run; removes untagged title-duplicates).

Portability / files:
- `zot tags-export [-o path]` → JSON of `{item-key: [tags]}` (key is stable across synced
  copies). `zot tags-import <path> [--dry-run]` re-applies on another machine. Use to move tag
  assignments across computers when native sync is unavailable.
- `zot mirror [-d ~/local/papers] [--copy] [--clean]` → browsable `Author/Year/Citekey-Title.pdf`
  symlink tree pointing at Zotero storage. **Local only, never syncs** — run on each machine.
- `zot note <id>` / `zot link <id>` / `zot related <id>` → Obsidian integration.

---

## Controlled tag vocabulary

Tags are the primary index. Keep to this scheme; **assign the 1–3 most salient _leaf_ tags**
(don't also add a parent, e.g. use `method/dms`, not also `method/chemical-mapping`).

- `method/` chemical-mapping, dms, shape, cryo-em, xray, nmr, fret, afm, ml, md, comput,
  single-molecule, native-gel, spr, rna-map-array
- `system/` ribosome, spliceosome, aptamer, riboswitch, ttr *(GAAA tetraloop/receptor)*,
  hammerhead, nanostructures, viral, kink-turn, tetra-ribozyme *(Tetrahymena ribozyme)*
- `topic/` secondary-structure, tertiary-structure, structure-prediction, rna-design,
  rna-dynamics, lab-automation, and `thermodynamics` (+ nested `thermodynamics/{tc, mg-binding,
  3d, ion-effects, ac-protonation, rna-protonation}` — a `contains topic/thermodynamics` search
  rolls these up)
- `type/` review, method, my-paper, benchmark, book
- workflow: `cited`, `cited/<project>`, `status/key-paper`, `status/important`, `lab/intro-paper`

The suggester (`src/zotero_cli/suggest.py`) holds the authoritative `VOCABULARY` set and refuses
to emit anything outside it. For semantic tagging of many papers, **read each title+abstract**
(fan out reader subagents) rather than trusting the keyword suggester — it's brittle on nuance.

---

## Collection conventions (folders)

Collections hold **work**, not topics (topics live in tags + Saved Searches). Structure:
`Projects/<project>` (active papers), `Writing/my-writings`, `Misc/` (topical folders with no
tag equivalent), `Inbox` (untriaged). Create projects with `zot new-project`. Deleting/merging
collections is best done in the Zotero GUI (clean deletion-sync).

---

## Common workflows

- **Import a folder of PDFs:** close Zotero → `zot scan <dir> --keep --dry-run` (preview) →
  `zot scan <dir> --keep`. Only PDFs with an extractable DOI are added; the rest are left in
  place. Not every PDF is a paper — verify by reading first-page text before bulk-adding a
  personal directory (Downloads/Documents contain forms, CVs, receipts, e-books).
- **Tag untagged papers:** `zot list --untagged`; read each abstract; `zot tag <id> <leaf-tag>`.
  Note: Zotero **annotations** and metadata-less stubs show up as untagged but are not papers.
- **New paper project:** `zot new-project 2026-foo` → file cited papers into `Projects/2026-foo`
  and tag them `cited/2026-foo`.
- **Cross-computer:** direct DB edits to *pre-existing* items don't auto-sync; either mark the
  changed items `synced=0` and re-sync (this machine wins), or `zot tags-export` here →
  `zot tags-import` there. New items/collections created by `zot` sync natively.

---

## Data locations & gotchas

- DB: `~/Zotero/zotero.sqlite` · files: `~/Zotero/storage/<KEY>/<file>` · backups:
  `~/Zotero/zotero.sqlite.bak-*`.
- Stored PDFs are named `Author+Year-Title.pdf` (see `build_filename`) for Finder search.
- CrossRef consortium authors have empty names → `add_item` skips them (Zotero rejects empty
  creators). Supplementary/SI PDFs and DOI-less papers (theses, pre-DOI scans) need judgment —
  the tooling can't auto-fetch metadata without a DOI (title-search CrossRef as a fallback).
- Unused tags are purged by Zotero on sync; a standalone tag persists only if **colored** (see
  `create_colored_tag`, used by `new-project`).
