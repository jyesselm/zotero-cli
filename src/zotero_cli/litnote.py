"""Literature-note pipeline: turn a Zotero PDF into the deterministic pieces of an
Obsidian literature note — real figure images, a paper-like cleaned reading note,
and a 'Cited in your notes' cross-link section.

This module owns only the *deterministic, read-only* half of the flow (extraction,
cleaning, figure clipping, citation matching). The executive summary (written by an
agent) and the final dashboard-note assembly (via the Obsidian MCP) stay a documented
manual step — see LITNOTES.md. `zot litnote <id>` runs everything here and drops a
JSON bundle the agent then uses.

Text-cleaning design notes (learned the hard way, keep them):
  * column-aware reading order (title/authors don't land mid-body),
  * de-hyphenation that keeps real compounds (single-chain) but merges soft breaks,
  * ligature + math-font normalization (ﬁ→fi, ð→( Þ→) ¼→= þ→+ À→−),
  * figure-internal / axis / table-cell text dropped, page furniture removed,
  * poppler re-spacing to fix glued words ("Networksoftriplehelices"),
  * markdown escaping of a fixed register so stray PDF chars can't corrupt rendering.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

# --------------------------------------------------------------------------- #
# regexes / constants
# --------------------------------------------------------------------------- #
CAP = re.compile(r"^\s*(Fig(?:ure)?\.?|Table|Scheme)\s*(\d+)", re.I)
REFHEAD = re.compile(
    r"(?im)^\s*(references|bibliography|references and notes|literature cited)\s*$"
)
REFSTOP = re.compile(
    r"^\s*(references|bibliography|references and notes|literature cited)\s*$", re.I
)
KNOWN = re.compile(
    r"^(abstract|introduction|results?|results and discussion|discussion|"
    r"conclusions?|methods|materials and methods|experimental|summary|background|"
    r"significance)\b",
    re.I,
)
ENDMATTER = re.compile(
    r"(?i)^(additional information|author contributions?|acknowled(g|)ements?|"
    r"competing (financial )?interests?|data availability|code availability|"
    r"reprints and permissions|peer review|publisher.s note|online content|extended data)"
)
ARTLABEL = re.compile(
    r"(?i)^(review|article|articles|perspective|letter|communication|report|"
    r"research article|mini-?review)$"
)
FURNITURE = re.compile(
    r"(?i)(downloaded via|sharing ?guidelines|^received on|^https?://|^see https?://|"
    r"pubs\.acs\.org/sharing|acs publications|dx\.doi\.org)"
)
LIG = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft",
    "ﬀ": "ff",
}
MATH = {"ð": "(", "Þ": ")", "þ": "+", "¼": "=", "À": "−"}


# --------------------------------------------------------------------------- #
# low-level text helpers
# --------------------------------------------------------------------------- #
def block_lines(b) -> list[str]:
    return ["".join(s["text"] for s in l["spans"]) for l in b["lines"]]


def _block_text(b) -> str:
    return "".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()


def collect_compounds(doc) -> set[str]:
    """Hyphenated compounds seen WITHIN a line -> keep their hyphen on line-break."""
    comp: Counter = Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for ln in block_lines(b):
                for m in re.findall(r"[A-Za-z]{2,}-[A-Za-z]{2,}", ln):
                    comp[m.lower()] += 1
    return set(comp)


def dehyphenate_join(lines: list[str], compounds: set[str]) -> str:
    if not lines:
        return ""
    text = lines[0].rstrip()
    for lt in lines[1:]:
        lt = lt.strip()
        if not lt:
            continue
        if text.endswith("-") and len(text) > 1 and text[-2].isalpha():
            base = text[:-1]
            prev = re.search(r"([A-Za-z]+)$", base)
            prev = prev.group(1) if prev else ""
            nxt = re.match(r"([A-Za-z]+)", lt)
            nxt = nxt.group(1) if nxt else ""
            if prev and nxt and f"{prev}-{nxt}".lower() in compounds:
                text = base + "-" + lt  # real compound -> keep hyphen
            else:
                text = base + lt  # soft hyphen -> merge word
        else:
            text = text + " " + lt
    return text


def normalize(s: str) -> str:
    for k, v in LIG.items():
        s = s.replace(k, v)
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", s)  # control chars
    for k, v in MATH.items():
        s = s.replace(k, v)
    for sp in (" ", " ", " "):
        s = s.replace(sp, " ")
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def md_escape(s: str) -> str:
    """Escape a fixed markdown register so stray PDF characters can't corrupt a note."""
    s = s.replace("\\", "\\\\")
    for ch in "*_`~<>[]":
        s = s.replace(ch, "\\" + ch)
    return re.sub(r"^(\s*)([#>|+\-])", r"\1\\\2", s)


def reading_order(page):
    pw, ph = page.rect.width, page.rect.height
    mid = pw / 2
    items = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        r = fitz.Rect(b["bbox"])
        txt = _block_text(b)
        if not txt:
            continue
        if (r.y1 < 0.07 * ph or r.y0 > 0.93 * ph) and len(txt) < 90:
            continue  # running head / footer
        if re.fullmatch(r"\d{1,4}", txt):
            continue  # page number
        items.append({"r": r, "b": b, "txt": txt})
    span_ys = sorted(it["r"].y0 for it in items if it["r"].width > 0.62 * pw)

    def key(it):
        r = it["r"]
        band = sum(1 for sy in span_ys if sy < r.y0 - 1)
        if r.width > 0.62 * pw:
            return (band, 0, 0, r.y0)
        col = 0 if (r.x0 + r.x1) / 2 < mid else 1
        return (band, 1, col, r.y0)

    items.sort(key=key)
    return items


def figure_regions(page):
    """Caption-anchored graphics-union rects (also used to drop figure-internal text)."""
    W, H = page.rect.width, page.rect.height

    def xov(a, b):
        return max(0, min(a.x1, b.x1) - max(a.x0, b.x0))

    caps = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        t = _block_text(b)
        if CAP.match(t) and len(t) >= 40:
            caps.append(fitz.Rect(b["bbox"]))
    gr = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            r = fitz.Rect(b["bbox"])
            if r.width > 20 and r.height > 20:
                gr.append(r)
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width > 4 and r.height > 4 and r.width < 0.98 * W and r.height < 0.95 * H:
            gr.append(r)
    regions = []
    for c in caps:
        inb = [r for r in gr if c.y0 >= r.y1 - 12 and xov(r, c) > 0.2 * min(r.width, c.width)]
        if inb:
            f = inb[0]
            for r in inb[1:]:
                f |= r
            regions.append(f)
    return regions


def junk2(txt: str) -> bool:
    """True for axis-number / panel-label / table-cell fragments (not prose)."""
    toks = txt.split()
    if len(toks) >= 3:
        short = sum(1 for t in toks if len(t) <= 2) / len(toks)
        numeric = sum(1 for t in toks if re.fullmatch(r"[\d.,%()Å–—-]+", t)) / len(toks)
        if short > 0.5 or numeric > 0.45:
            return True
    if txt.count("?") >= 3:
        return True
    a = sum(c.isalpha() for c in txt)
    if len(txt) < 120 and (a / max(1, len(txt))) < 0.55:
        return True
    return False


def _inside_figure(r, regs) -> bool:
    return any(
        r.get_area() > 0
        and (max(0, min(r.x1, fr.x1) - max(r.x0, fr.x0)))
        * (max(0, min(r.y1, fr.y1) - max(r.y0, fr.y0)))
        / r.get_area()
        > 0.55
        for fr in regs
    )


# --------------------------------------------------------------------------- #
# poppler re-spacing (fixes glued words from PyMuPDF spans)
# --------------------------------------------------------------------------- #
def poppler_index(path: str):
    try:
        txt = subprocess.run(
            ["pdftotext", path, "-"], capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return "", "", []
    ns, mp = [], []
    for i, c in enumerate(txt):
        if c.isalnum():
            ns.append(c.lower())
            mp.append(i)
    return txt, "".join(ns), mp


def respace(para: str, pt: str, pns: str, pmp: list[int]) -> str:
    para = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", para)
    if not pt or len(para) < 8:
        return para
    key = re.sub(r"[^a-z0-9]", "", para.lower())
    if len(key) < 8:
        return para
    j = pns.find(key)
    if j < 0:
        return para
    seg = pt[pmp[j] : pmp[j + len(key) - 1] + 1]
    return re.sub(r"[\x00-\x08\x0b-\x1f]", " ", re.sub(r"\s+", " ", seg)).strip()


# --------------------------------------------------------------------------- #
# figure extraction + references + cleaned text  ->  bundle
# --------------------------------------------------------------------------- #
def _graphics(page):
    W, H = page.rect.width, page.rect.height
    g = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            r = fitz.Rect(b["bbox"])
            if r.width > 20 and r.height > 20:
                g.append(r)
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width > 4 and r.height > 4 and r.width < 0.98 * W and r.height < 0.95 * H:
            g.append(r)
    return g


def clean_text(path: str) -> str:
    """Column-aware, de-hyphenated, normalized body text (references stripped)."""
    doc = fitz.open(path)
    compounds = collect_compounds(doc)
    paras = []
    for page in doc:
        regs = figure_regions(page)
        for it in reading_order(page):
            r, txt, b = it["r"], it["txt"], it["b"]
            if CAP.match(txt):
                continue
            if junk2(txt):
                continue
            if _inside_figure(r, regs):
                continue
            if REFSTOP.match(txt):
                doc.close()
                return "\n\n".join(paras)
            para = normalize(dehyphenate_join(block_lines(b), compounds))
            if len(para) > 1:
                paras.append(para)
    doc.close()
    return "\n\n".join(paras)


def extract_references(path: str) -> tuple[str, int]:
    """Return (references_text, n_refs) for a PDF — the trailing reference list.

    Cheap (text only, no figure clipping): used by `zot relink` to recompute
    cross-links against the current vault without a full rebuild.
    """
    doc = fitz.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    refs = ""
    mh = None
    for m in REFHEAD.finditer(text):
        mh = m  # last match = real refs section
    if mh:
        refs = text[mh.end() :]
    if len(refs) < 2000:  # headingless -> numbered-list fallback
        m1 = re.search(r"(?m)^\s*[\(\[]?1[\)\].]\s+[A-Z]", text)
        if (
            m1
            and re.search(r"(?m)^\s*[\(\[]?2[\)\].]\s", text[m1.start() : m1.start() + 5000])
            and re.search(r"(?m)^\s*[\(\[]?3[\)\].]\s", text[m1.start() : m1.start() + 8000])
        ):
            cand = text[m1.start() :]
            if len(cand) > len(refs):
                refs = cand
    if refs:
        refs = re.split(
            r"(?im)^\s*(acknowledg|author contributions|supplementary|competing interest|extended data)",
            refs,
        )[0]
    ref_n = len(re.findall(r"(?m)^\s*[\(\[]?\d+[\)\].]?\s+[A-Z]", refs)) if refs else 0
    return refs, ref_n


def extract(path: str, out_dir: Path, slug: str) -> dict:
    """Clip figures, capture captions + references, write cleaned text. Returns bundle.

    Emits a figure image ONLY when real graphics exist under the caption; otherwise
    the figure is recorded caption-only (never a fake image / broken embed).
    """
    def xov(a, b):
        return max(0, min(a.x1, b.x1) - max(a.x0, b.x0))

    doc = fitz.open(path)
    figdir = out_dir / "attachments" / slug
    figdir.mkdir(parents=True, exist_ok=True)
    for f in figdir.glob("fig*.png"):
        f.unlink()

    figures = []
    seen: set[str] = set()
    full = []
    for pno, page in enumerate(doc):
        full.append(page.get_text())
        bl = [(fitz.Rect(b["bbox"]), _block_text(b), b) for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        gr = _graphics(page)
        caps = [
            [r, f"{m.group(1).lower().rstrip('.')}{m.group(2)}", t]
            for r, t, _ in bl
            if (m := CAP.match(t)) and len(t) >= 40
        ]
        assign = {i: [] for i in range(len(caps))}
        for rg in gr:
            best, bd = -1, 1e9
            for i, (cr, _, _) in enumerate(caps):
                if cr.y0 >= rg.y1 - 12 and xov(rg, cr) > 0.2 * min(rg.width, cr.width) and cr.y0 - rg.y1 < bd:
                    bd = cr.y0 - rg.y1
                    best = i
            if best >= 0:
                assign[best].append(rg)
        for i, (cr, label, cap) in enumerate(caps):
            if label in seen:
                continue
            seen.add(label)
            fig = None
            for rg in assign[i]:
                fig = rg if fig is None else fig | rg
            rec = {"label": label, "page": pno + 1, "caption": cap}
            if fig and fig.width >= 40 and fig.height >= 40:
                pad = fitz.Rect(fig.x0 - 4, fig.y0 - 4, fig.x1 + 4, fig.y1 + 4) & page.rect
                fn = figdir / f"{label}.png"
                page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), clip=pad).save(fn)
                rec["image"] = str(fn)
                rec["tier"] = "clip"
            else:
                rec["image"] = None
                rec["tier"] = "caption-only"
            figures.append(rec)

    text = "\n".join(full)
    doc.close()
    refs, ref_n = extract_references(path)

    bundle = {
        "slug": slug,
        "pages": len(full),
        "chars": len(text),
        "figures": figures,
        "n_fig_img": sum(1 for f in figures if f["image"]),
        "n_fig_total": len(figures),
        "references": refs,
        "references_n": ref_n,
    }
    return bundle


# --------------------------------------------------------------------------- #
# paper-like reading note (headings + inline figures + markdown-safe prose)
# --------------------------------------------------------------------------- #
def _body_font(doc) -> float:
    c: Counter = Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    if len(s["text"].strip()) > 1:
                        c[round(s["size"])] += len(s["text"])
    return c.most_common(1)[0][0] if c else 10


def _block_meta(b):
    sizes = [s["size"] for l in b["lines"] for s in l["spans"] if s["text"].strip()]
    bold = any((s["flags"] & 16) for l in b["lines"] for s in l["spans"] if s["text"].strip())
    return (max(sizes) if sizes else 0), bold


def _runin_split(b):
    spans = [s for l in b["lines"] for s in l["spans"]]
    head = []
    i = 0
    while i < len(spans) and (spans[i]["flags"] & 16 or not spans[i]["text"].strip()):
        head.append(spans[i]["text"])
        i += 1
    h = "".join(head).strip()
    if 3 <= len(h.split()) <= 14 and "".join(s["text"] for s in spans[i:]).strip() and not h.endswith("."):
        return h
    return None


def build_reading_note(path: str, slug: str, fig_by_label: dict, title: str = "") -> str:
    """Reconstruct a readable, markdown-safe paper body with inline figures."""
    doc = fitz.open(path)
    npages = doc.page_count
    comp = collect_compounds(doc)
    bf = _body_font(doc)
    pt, pns, pmp = poppler_index(path)
    out = (["# " + md_escape(title) + "\n"] if title else [])
    emitted: set[str] = set()
    dropcap = ""
    intable = False
    tnorm = re.sub(r"[^a-z0-9]", "", (title or "").lower())
    buf: list[str] = []
    prev = None

    def flush():
        nonlocal buf, dropcap
        if not buf:
            return
        para = respace(normalize(dehyphenate_join(buf, comp)), pt, pns, pmp)
        if dropcap:
            para = dropcap + para
            dropcap = ""
        if len(para) > 1:
            out.append(md_escape(para))
        buf = []

    for page in doc:
        regs = figure_regions(page)
        for it in reading_order(page):
            b, txt, r = it["b"], it["txt"], it["r"]
            m = CAP.match(txt)
            if m and len(txt) >= 40:
                flush()
                prev = None
                label = f"{m.group(1).lower().rstrip('.')}{m.group(2)}"
                if label in emitted:
                    continue
                emitted.add(label)
                cap = md_escape(respace(normalize(dehyphenate_join(block_lines(b), comp)), pt, pns, pmp))
                if fig_by_label.get(label, {}).get("image"):
                    out.append(f"\n![[attachments/{slug}/{label}.png]]")
                if " | " in cap:
                    a, b2 = cap.split(" | ", 1)
                    out.append(f"> **{a} |** {b2}\n")
                else:
                    out.append(f"> {cap}\n")
                intable = label.startswith("table")
                continue
            if junk2(txt) or FURNITURE.search(txt):
                continue
            if _inside_figure(r, regs):
                continue
            # End-matter/references stop — but ONLY in the latter part of the paper.
            # Some journals (e.g. PNAS, Nature) print "Author contributions" /
            # "Competing interests" in page-1 furniture; matching those early would
            # truncate the whole body. Before the halfway point, skip the block instead.
            if REFSTOP.match(txt) or ENDMATTER.match(txt):
                if page.number >= max(1, npages // 2):
                    flush()
                    doc.close()
                    return "\n".join(out)
                continue  # front-matter furniture — drop this block, keep reading
            mx, bold = _block_meta(b)
            wc = len(txt.split())
            if intable:
                if wc >= 12 and txt.rstrip().endswith("."):
                    intable = False
                else:
                    continue
            al = [c for c in txt if c.isalpha()]
            upper = (sum(c.isupper() for c in al) / len(al)) if al else 0
            caps = sum(1 for w in txt.split() if w[:1].isupper())
            is_author = (2 <= wc <= 40) and (
                upper > 0.7
                or any(d in txt for d in "†‡§")
                or (page.number == 0 and caps >= wc * 0.6 and (" and " in " " + txt.lower() + " " or txt.count(",") >= 1))
            )
            if tnorm and page.number == 0 and mx >= bf * 1.2 and len(txt) > 3 and re.sub(r"[^a-z0-9]", "", normalize(txt).lower()) in tnorm:
                continue
            if ARTLABEL.match(txt.strip()):
                continue
            if len(txt.strip()) <= 1 and mx >= bf * 1.3:
                flush()
                dropcap = txt.strip()
                prev = None
                continue
            if wc <= 12 and len(txt.strip()) >= 3 and not txt.endswith(".") and (mx >= bf * 1.15 or KNOWN.match(txt)) and not is_author:
                flush()
                out.append(f"\n## {md_escape(respace(normalize(txt), pt, pns, pmp))}\n")
                prev = None
                continue
            head = _runin_split(b)
            if head:
                flush()
                full = normalize(dehyphenate_join(block_lines(b), comp))
                body = full[len(head) :].strip() if full.startswith(head) else full
                out.append(f"\n### {md_escape(respace(normalize(head), pt, pns, pmp))}\n")
                if body:
                    out.append(md_escape(respace(body, pt, pns, pmp)))
                prev = None
                continue
            # body block: coalesce with previous if tight vertical gap in same column
            if prev is not None and (r.y0 - prev.y1) < 0.6 * bf and (min(r.x1, prev.x1) - max(r.x0, prev.x0)) > 0.4 * min(r.width, prev.width):
                buf.extend(block_lines(b))
            else:
                flush()
                buf = block_lines(b)
            prev = r
    flush()
    doc.close()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# citation linking: match references to library items that HAVE notes
# --------------------------------------------------------------------------- #
def vault_key2slug(science_dir: Path) -> dict:
    """{zotero_key: slug} for every existing literature note (skips .fulltext)."""
    m = {}
    for f in science_dir.glob("*.md"):
        if f.name.endswith(".fulltext.md"):
            continue
        km = re.search(r"zotero_key:\s*[\"']?(\w+)", f.read_text()[:800])
        if km:
            m[km.group(1)] = f.stem
    return m


def match_item(reftext: str, lib) -> object | None:
    """Return the library item cited by a reference entry, or None (DOI > author+year > title)."""
    rt = reftext.lower()
    rta = re.sub(r"[^a-z0-9 ]", "", rt)
    for it in lib:
        if it.doi and it.doi.lower() in rt:
            return it
    for it in lib:
        if len(it.first_author) >= 4 and it.year and it.first_author.lower() in rt and it.year in rt:
            return it
    for it in lib:
        if it.title and len(it.title) > 40 and re.sub(r"[^a-z0-9 ]", "", it.title.lower())[:45] in rta:
            return it
    return None


def parse_numbered_refs(reftext: str) -> dict:
    """Split a numbered reference list into {num: entry_text}."""
    refs = {}
    parts = re.split(r"(?m)^\s*[\(\[]?(\d{1,3})[\)\].]\s+", "\n" + reftext)
    for i in range(1, len(parts) - 1, 2):
        try:
            refs[int(parts[i])] = parts[i + 1][:400]
        except Exception:
            pass
    return refs


def cited_notes(reftext: str, self_key: str, noted_items, key2slug: dict):
    """-> (section, num2slug).
       section  = [(slug, item, refnum|None)] for cited items that have notes,
       num2slug = {refnum: slug} for inline linking.
    """
    noted = [it for it in noted_items if it.key in key2slug and it.key != self_key]
    num2slug, slug2num = {}, {}
    for num, entry in parse_numbered_refs(reftext).items():
        mi = match_item(entry, noted)
        if mi:
            num2slug[num] = key2slug[mi.key]
            slug2num.setdefault(key2slug[mi.key], num)
    section, seen = [], set()
    for it in noted:
        slug = key2slug[it.key]
        if match_item(reftext, [it]) and slug not in seen:
            seen.add(slug)
            section.append((slug, it, slug2num.get(slug)))
    return section, num2slug


def cited_section_md(section, self_slug: str) -> str:
    """Render the 'Cited in your notes' managed region (or '' if nothing cited)."""
    if not section:
        return ""
    lines = [
        "<!-- zot:auto:start:cited -->",
        "## Cited in your notes",
        "Papers cited here that you also keep literature notes on — follow the link to "
        "the note, or the ref # to find the citation in the "
        f"[[{self_slug}.fulltext#References|reference list]]:",
    ]
    for slug, it, num in sorted(section, key=lambda x: (x[2] or 9999)):
        ref = f" — ref **#{num}**" if num else ""
        title = (it.title or "")[:70]
        lines.append(f"- [[{slug}|{it.first_author} et al. {it.year}]]{ref} · *{title}*")
    lines.append("<!-- zot:auto:end:cited -->")
    return "\n".join(lines)


def set_cited_region(note_text: str, cited_md: str) -> str:
    """Insert/replace/remove the zot:auto:cited managed region in a dashboard note.

    - region present + cited_md non-empty -> replace it
    - region present + cited_md empty      -> remove it
    - region absent  + cited_md non-empty  -> insert right after the summary region
      (or, failing that, before the figures region)
    Everything else in the note is untouched.
    """
    start, end = "<!-- zot:auto:start:cited -->", "<!-- zot:auto:end:cited -->"
    if start in note_text and end in note_text:
        pre = note_text[: note_text.index(start)]
        post = note_text[note_text.index(end) + len(end) :]
        if not cited_md:
            # drop region and one trailing blank line
            return pre.rstrip("\n") + "\n\n" + post.lstrip("\n")
        return pre + cited_md + post
    if not cited_md:
        return note_text
    anchor = "<!-- zot:auto:end:summary -->"
    if anchor in note_text:
        i = note_text.index(anchor) + len(anchor)
        return note_text[:i] + "\n\n" + cited_md + note_text[i:]
    anchor = "<!-- zot:auto:start:figures -->"
    if anchor in note_text:
        i = note_text.index(anchor)
        return note_text[:i] + cited_md + "\n\n" + note_text[i:]
    return note_text  # no anchors — leave untouched


_AFFIL = re.compile(
    r"(Department|University|Institute|Laborator|e-mail|@|School of|Center for|"
    r"Howard Hughes|Correspond)"
)


def link_inline(body: str, num2slug: dict):
    """Wrap citation numbers of noted refs with links, in PROSE only. Conservative +
    reversible. Only links AFTER the first '## ' section heading, so the author/
    affiliation front matter (where names carry the same superscript digits as
    citation markers, e.g. 'Carlson8') is never touched. Ranges (7-10) are ambiguous
    and left alone. Still spot-check: superscripts can collide with a real cite number.
    """
    if not num2slug:
        return body, 0
    n = [0]

    def repl(m):
        pre, grp = m.group(1), m.group(2)
        if re.search(r"[–\-]", grp):  # ambiguous range -> never link
            return pre + grp
        out = []
        for t in re.split(r"([,])", grp):
            if t.isdigit() and int(t) in num2slug:
                out.append(f"[[{num2slug[int(t)]}|{t}]]")
                n[0] += 1
            else:
                out.append(t)
        return pre + "".join(out)

    lines, in_body = [], False
    for ln in body.split("\n"):
        if not in_body:
            if ln.startswith("## "):
                in_body = True
            lines.append(ln)
            continue
        if ln.startswith(("#", ">", "!", "[[")) or _AFFIL.search(ln) or len(ln) < 40:
            lines.append(ln)
            continue
        lines.append(
            re.sub(
                r"(?<![0-9])([a-z\)\.,])(\d{1,3}(?:[,–\-]\d{1,3})*)(?=[\s\.,;\)]|$)",
                repl,
                ln,
            )
        )
    return "\n".join(lines), n[0]


# --------------------------------------------------------------------------- #
# orchestration helpers
# --------------------------------------------------------------------------- #
def dashboard_mocs(paper_tags) -> list[str]:
    """MOC slugs a note links: one per method/system/topic/type tag, one per
    cited/<project> ('papers to write'), + a key-papers floor."""
    out, seen = [], set()
    for t in paper_tags:
        mt = _moc_tag(t)
        if not mt and t.startswith("cited/"):
            mt = t  # group by the manuscript that cites this paper
        if mt:
            slug = "MOC - " + mt.replace("/", "-")
            if slug not in seen:
                seen.add(slug)
                out.append(slug)
    if any(t == "status/key-paper" for t in paper_tags) and "MOC - key-papers" not in seen:
        out.append("MOC - key-papers")
    return out


def moc_region_md(paper_tags) -> str:
    """Render the zot:auto:moc managed region body."""
    mocs = dashboard_mocs(paper_tags)
    links = " · ".join(f"[[{m}]]" for m in mocs) if mocs else "*(no MOC tags)*"
    return f"<!-- zot:auto:start:moc -->\n## MOCs\n{links}\n<!-- zot:auto:end:moc -->"


def set_region(note_text: str, name: str, body: str, after: str = None, before: str = None) -> str:
    """Insert/replace/remove a zot:auto:<name> managed region (see set_cited_region)."""
    start, end = f"<!-- zot:auto:start:{name} -->", f"<!-- zot:auto:end:{name} -->"
    if start in note_text and end in note_text:
        pre = note_text[: note_text.index(start)]
        post = note_text[note_text.index(end) + len(end) :]
        return (pre.rstrip("\n") + "\n\n" + post.lstrip("\n")) if not body else (pre + body + post)
    if not body:
        return note_text
    if after and after in note_text:
        i = note_text.index(after) + len(after)
        return note_text[:i] + "\n\n" + body + note_text[i:]
    if before and before in note_text:
        i = note_text.index(before)
        return note_text[:i] + body + "\n\n" + note_text[i:]
    return note_text


def _yaml_scalar(v) -> str:
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{}&*!|>'\"%@`]", s) or s != s.strip():
        return "'" + s.replace("'", "''") + "'"
    return s


def render_dashboard(
    *, slug, key, title, authors, year, journal, doi, url, paper_tags,
    figures, summary, cited_md, status="unread", date="2026-07-04", updated="2026-07-04",
) -> str:
    """Render a complete dashboard note (YAML frontmatter + managed-region body).

    `figures` is the bundle's figure list ({label, caption, image}). `summary` is the
    agent-written executive summary; `cited_md` the 'Cited in your notes' region ('' if none).
    """
    n_img = sum(1 for f in figures if f.get("image"))
    fm = [
        ("title", title), ("year", year), ("journal", journal), ("doi", doi),
        ("url", url), ("citekey", f"{(authors[0].split()[-1] if authors else '')}{year}"),
        ("zotero_key", key), ("zotero", f"zotero://select/library/items/{key}"),
        ("type", "literature"),
    ]
    lines = ["---"]
    for k, v in fm:
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("authors:")
    for a in authors:
        lines.append(f"  - {_yaml_scalar(a)}")
    lines.append("tags:")
    lines.append("  - literature")
    lines.append("paper-tags:")
    for t in paper_tags:
        lines.append(f"  - {t}")
    for k, v in [("status", status), ("date", date), ("updated", updated),
                 ("zot_built", "2026-07-04"), ("zot_pipeline", 5),
                 ("figures", n_img), ("has_fulltext", "true")]:
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")

    first = authors[0].split()[-1] if authors else ""
    last = authors[-1].split()[-1] if len(authors) > 1 else ""
    byline = f"{first}, … {last}" if last and last != first else first
    doi_link = f" · [{doi}](https://doi.org/{doi})" if doi else ""
    mocs = dashboard_mocs(paper_tags)

    b = lines
    b.append(f"# {title}\n")
    b.append(f"**{byline}** · {year} · *{journal}*{doi_link}\n")
    b.append("## Links")
    b.append(f"- **Zotero:** [open in Zotero](zotero://select/library/items/{key})")
    b.append(f"- **PDF:** [open PDF](zotero://open-pdf/library/items/{key})")
    b.append(f"- **Full extracted text:** [[{slug}.fulltext|read full text]]\n")
    b.append("<!-- zot:auto:start:moc -->")
    b.append("## MOCs")
    b.append(" · ".join(f"[[{m}]]" for m in mocs) if mocs else "*(no MOC tags)*")
    b.append("<!-- zot:auto:end:moc -->\n")
    b.append("## Summary")
    b.append("<!-- zot:auto:start:summary -->")
    b.append(summary.strip())
    b.append("<!-- zot:auto:end:summary -->\n")
    if cited_md:
        b.append(cited_md + "\n")
    b.append("<!-- zot:auto:start:figures -->")
    b.append("## Figures\n")
    for f in figures:
        if not f.get("image"):
            continue
        num = re.sub(r"\D", "", f["label"])
        cap = md_escape(f["caption"].strip())
        b.append(f"### Figure {num}")
        b.append(f"![[attachments/{slug}/{f['label']}.png]]")
        if " | " in cap:
            a, b2 = cap.split(" | ", 1)
            b.append(f"> **{a} |** {b2}\n")
        else:
            b.append(f"> {cap}\n")
    caponly = [f["label"] for f in figures if not f.get("image")]
    if caponly:
        b.append(f"*Caption-only (no extractable graphics): {', '.join(caponly)} — see the "
                 f"[open PDF](zotero://open-pdf/library/items/{key}).*\n")
    b.append("<!-- zot:auto:end:figures -->\n")
    b.append("<!-- zot:auto:start:text -->")
    b.append("## Extracted text")
    b.append("The complete machine-extracted body is in the sibling note:\n")
    b.append(f"→ [[{slug}.fulltext|Full extracted text]]")
    b.append("<!-- zot:auto:end:text -->\n")
    b.append("## Notes")
    b.append("*Your notes live here and below — never touched when this note is regenerated.*\n")
    b.append("## Key Points")
    b.append("- \n")
    b.append("## Questions")
    b.append("- ")
    return "\n".join(b) + "\n"


def merge_preserving_human(old: str, fresh: str) -> str:
    """Regeneration: keep human-owned frontmatter (status/updated) and everything from
    the first human section (## Notes) onward from `old`; take the rest from `fresh`."""
    # human body tail
    marker = "\n## Notes"
    fresh_head = fresh.split(marker, 1)[0]
    old_tail = old.split(marker, 1)
    tail = marker + old_tail[1] if len(old_tail) == 2 else fresh[len(fresh_head):]
    merged = fresh_head + tail
    # preserve human frontmatter values
    for keyname in ("status", "updated"):
        m = re.search(rf"(?m)^{keyname}:\s*(.*)$", old)
        if m:
            merged = re.sub(rf"(?m)^{keyname}:\s*.*$", f"{keyname}: {m.group(1).strip()}", merged, count=1)
    return merged


def _read_frontmatter(path: Path) -> dict:
    """Minimal YAML-ish frontmatter reader (title, year, journal, paper-tags list)."""
    txt = path.read_text()
    if not txt.startswith("---"):
        return {}
    end = txt.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    block = txt[3:end]
    key = None
    for line in block.split("\n"):
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val and val not in ("|", ">"):
                fm[key] = val.strip("'\"")
            else:
                fm[key] = []
        elif key and re.match(r"^\s*-\s+", line):
            item = re.sub(r"^\s*-\s+", "", line).strip().strip("'\"")
            if isinstance(fm.get(key), list):
                fm[key].append(item)
            else:
                fm[key] = [item]
    return fm


def _moc_tag(tag: str) -> str | None:
    """Map a paper-tag to its MOC bucket, or None if the tag doesn't get a MOC.
    method/system/topic/type get MOCs; topic/thermodynamics/* rolls up to
    topic/thermodynamics. status/cited/lab do not (key-papers is a separate floor)."""
    cat = tag.split("/")[0]
    if cat not in ("method", "system", "topic", "type"):
        return None
    if tag.startswith("topic/thermodynamics"):
        return "topic/thermodynamics"
    return tag


def build_mocs(science_dir: Path) -> list[str]:
    """(Re)generate MOC - <tag> notes under <science_dir>/MOCs/ from the corpus.

    Each MOC = a Dataview query (auto-updating) + a marker-fenced static wikilink
    list (resolves even without Dataview). A floor 'MOC - key-papers' collects every
    status/key-paper note so each note links at least one MOC. Human text below the
    fence is preserved. Returns the list of MOC slugs written.
    """
    notes = []
    for f in sorted(science_dir.glob("*.md")):
        if f.name.endswith(".fulltext.md") or f.stem.startswith("MOC - "):
            continue
        fm = _read_frontmatter(f)
        tags = fm.get("paper-tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        notes.append(
            {
                "slug": f.stem,
                "title": fm.get("title", f.stem),
                "year": fm.get("year", ""),
                "tags": tags,
            }
        )

    # bucket notes by MOC tag (+ floor). method/system/topic/type AND cited/<project>
    # (the latter = "papers cited in a manuscript you're writing").
    buckets: dict[str, list] = {}
    for n in notes:
        seen = set()
        for t in n["tags"]:
            mt = _moc_tag(t)
            if not mt and t.startswith("cited/"):
                mt = t
            if mt and mt not in seen:
                seen.add(mt)
                buckets.setdefault(mt, []).append(n)
        if any(t == "status/key-paper" for t in n["tags"]):
            buckets.setdefault("__key-papers__", []).append(n)

    mocdir = science_dir / "MOCs"
    mocdir.mkdir(exist_ok=True)
    written = []
    for tag, members in sorted(buckets.items()):
        if tag == "__key-papers__":
            slug, heading, where = "MOC - key-papers", "Key papers", 'contains(paper-tags, "status/key-paper")'
        elif tag.startswith("cited/"):
            slug = "MOC - " + tag.replace("/", "-")
            heading = f"Papers cited in — {tag.split('/', 1)[1]}"
            where = f'contains(paper-tags, "{tag}")'
        else:
            slug = "MOC - " + tag.replace("/", "-")
            heading = tag
            where = f'contains(paper-tags, "{tag}")'
        rows = "\n".join(
            f"- [[{m['slug']}]]" + (f" ({m['year']})" if m["year"] else "")
            for m in sorted(members, key=lambda m: (str(m["year"]), m["slug"]))
        )
        body = (
            f"---\ntype: moc\ntags: [moc]\nzot_built: '2026-07-04'\n---\n"
            f"# {heading}\n\n"
            f"Papers tagged `{'status/key-paper' if tag=='__key-papers__' else tag}` "
            f"({len(members)}). Auto-generated by `zot moc-sync` — edit below the fence.\n\n"
            f"```dataview\nTABLE year, journal FROM \"300-reference/science\"\n"
            f"WHERE {where}\nSORT year ASC\n```\n\n"
            f"<!-- zot:auto:start:list -->\n## Notes\n{rows}\n<!-- zot:auto:end:list -->\n"
        )
        path = mocdir / f"{slug}.md"
        # preserve any human text below the fence
        if path.exists():
            old = path.read_text()
            tail = old.split("<!-- zot:auto:end:list -->", 1)
            if len(tail) == 2 and tail[1].strip():
                body = body.rstrip("\n") + tail[1]
        path.write_text(body)
        written.append(slug)
    return written


def make_slug(item) -> str:
    """firstauthor-year-shorttitle (lowercase-hyphen), matching the vault convention."""
    author = re.sub(r"[^a-z]", "", item.first_author.lower()) or "anon"
    year = item.year or "n-d"
    words = re.findall(r"[a-z0-9]+", (item.title or "").lower())
    stop = {"the", "a", "an", "of", "and", "in", "for", "to", "on", "with", "by", "from"}
    kept = [w for w in words if w not in stop][:6]
    tail = "-".join(kept)
    return f"{author}-{year}-{tail}".strip("-")
