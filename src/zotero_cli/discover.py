"""Reading-list discovery: surface papers you should read, mined from what your
existing notes already cite. Produces a LIST for review — never adds anything to
Zotero (per-paper approval is the user's).

Signal A (self-contained): co-citation gaps. Every literature note has a cached
`<slug>.references.txt`. A work cited by MANY of your papers that you don't already
own is a strong "you should read this" candidate. We cluster the ~4-5k references by
(first-author, year), drop anything already in your library (via litnote.match_item),
and rank by how many distinct notes cite it.

Signals B (forward citations via OpenAlex) and C (facet-similarity) live in the CLI
command and are opt-in / external.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from zotero_cli.litnote import match_item, parse_numbered_refs, vault_key2slug

OPENALEX = "https://api.openalex.org"
_UA = {"User-Agent": "zotero-cli-discover (mailto:skullnite@gmail.com)"}

_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
# first author surname: leading capitalized token (handles "Cate, J.H." / "Michel, F. &")
_SURNAME = re.compile(r"[A-Z][A-Za-z][A-Za-z'À-ſ-]+")
_STOP = {"the", "and", "for", "with", "from", "that", "this", "into", "via", "using",
         "structure", "structural", "rna", "analysis", "role", "roles"}


def _entries(text: str) -> list[str]:
    """Split a references.txt into individual reference strings."""
    refs = parse_numbered_refs(text)
    if len(refs) >= 3:
        return [re.sub(r"\s+", " ", v).strip() for v in refs.values()]
    # fallback: blank-line / newline-separated blocks
    return [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n(?=\s*[A-Z])", text) if len(b.strip()) > 30]


def _signature(entry: str) -> tuple[str, str] | None:
    """(surname_lower, year) — the clustering key. None if unparseable."""
    ym = list(_YEAR.finditer(entry))
    if not ym:
        return None
    year = ym[-1].group(1)  # publication year is usually the last one in the string
    sm = _SURNAME.search(entry)
    if not sm:
        return None
    return (sm.group(0).lower(), year)


def _title_tokens(entry: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", entry.lower()) if w not in _STOP}


def cocitation_gaps(science_dir: Path, lib, min_notes: int = 2) -> list[dict]:
    """Rank works cited by >=min_notes of your notes that you don't already own.

    Returns dicts: {count, notes:[slug], year, surname, ref (representative string)}.
    """
    key2slug = vault_key2slug(science_dir)
    self_slugs = set(key2slug.values())

    clusters: dict[tuple, dict] = defaultdict(
        lambda: {"notes": set(), "refs": [], "toks": None}
    )
    for rf in science_dir.glob("*.references.txt"):
        slug = rf.name[: -len(".references.txt")]
        for entry in _entries(rf.read_text()):
            sig = _signature(entry)
            if not sig:
                continue
            c = clusters[sig]
            c["notes"].add(slug)
            if len(c["refs"]) < 5:
                c["refs"].append(entry)

    out = []
    for (surname, year), c in clusters.items():
        if len(c["notes"]) < min_notes:
            continue
        rep = max(c["refs"], key=len)  # the fullest citation string
        # already in your library? (DOI / author+year / title match)
        if match_item(rep, lib):
            continue
        out.append({
            "count": len(c["notes"]),
            "notes": sorted(c["notes"]),
            "surname": surname,
            "year": year,
            "ref": rep,
        })
    out.sort(key=lambda d: (-d["count"], d["surname"]))
    return out


# --------------------------------------------------------------------------- #
# Signals B & C — external (OpenAlex, open API, no key). Read-only lookups.
# --------------------------------------------------------------------------- #
def _oa_get(path: str, **params) -> dict | None:
    url = f"{OPENALEX}/{path}?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _owned(lib) -> tuple[set, list]:
    """(set of owned DOIs lowercased, list of lib items) for dedup."""
    dois = {it.doi.lower() for it in lib if it.doi}
    return dois, lib


def _clean_doi(doi: str | None) -> str:
    if not doi:
        return ""
    return doi.lower().replace("https://doi.org/", "").strip()


def forward_citations(lib, key_items, per_paper: int = 40, min_year: int = 2015) -> list[dict]:
    """Signal B: recent papers that CITE your key papers, not already owned, ranked by
    how many of your key papers they cite (then recency)."""
    owned_dois, _ = _owned(lib)
    agg: dict[str, dict] = {}
    for it in key_items:
        doi = _clean_doi(it.doi)
        if not doi:
            continue
        work = _oa_get(f"works/doi:{doi}")
        if not work or not work.get("id"):
            continue
        wid = work["id"].rsplit("/", 1)[-1]
        res = _oa_get("works", filter=f"cites:{wid},from_publication_date:{min_year}-01-01",
                      select="id,doi,title,publication_year,cited_by_count,primary_location",
                      sort="cited_by_count:desc", per_page=per_paper)
        for w in (res or {}).get("results", []):
            wd = _clean_doi(w.get("doi"))
            if wd and wd in owned_dois:
                continue
            k = w["id"]
            if k not in agg:
                venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
                agg[k] = {"title": w.get("title") or "", "year": w.get("publication_year"),
                          "cites_n": w.get("cited_by_count", 0), "doi": wd, "venue": venue,
                          "via": set()}
            agg[k]["via"].add(f"{it.first_author} {it.year}")
    out = [{**v, "via": sorted(v["via"])} for v in agg.values() if v["title"]]
    out.sort(key=lambda d: (-len(d["via"]), -(d["cites_n"] or 0)))
    return out


# facet leaf -> a precise search phrase (so OpenAlex keyword search isn't noisy).
_PHRASE = {
    "smfret": "single-molecule FRET", "single-molecule": "single-molecule RNA folding",
    "dms": "DMS chemical probing RNA", "dms-mapseq": "DMS-MaPseq", "shape": "SHAPE probing RNA",
    "shape-mapseq": "SHAPE-MaP", "chemical-mapping": "RNA chemical probing",
    "mutate-and-map": "mutate-and-map RNA", "inline-probing": "in-line probing RNA",
    "hydroxyl-radical-footprinting": "hydroxyl radical footprinting RNA",
    "cryo-em": "cryo-EM RNA structure", "xray": "RNA crystal structure", "nmr": "RNA NMR structure",
    "saxs": "RNA small-angle X-ray scattering", "itc": "RNA isothermal titration calorimetry",
    "rosetta-farfar": "FARFAR RNA structure modeling", "structure-prediction": "RNA structure prediction",
    "md": "RNA molecular dynamics simulation", "rna-map-array": "high-throughput RNA array",
    "stopped-flow": "stopped-flow RNA folding kinetics", "equilibrium-titration": "RNA Mg2+ folding",
    # systems
    "group-i-intron": "group I intron ribozyme", "group-ii-intron": "group II intron",
    "ttr": "GAAA tetraloop receptor", "tetraloop": "RNA tetraloop", "p4-p6": "P4-P6 domain RNA",
    "kink-turn": "RNA kink-turn motif", "a-minor": "A-minor motif RNA", "pseudoknot": "RNA pseudoknot",
    "riboswitch": "riboswitch", "aptamer": "RNA aptamer", "tetra-ribozyme": "Tetrahymena ribozyme",
    "hammerhead": "hammerhead ribozyme", "rnase-p": "RNase P RNA", "ribosome": "ribosome structure",
    "rrna": "ribosomal RNA structure", "trna": "tRNA structure", "spliceosome": "spliceosome",
    "snrna": "snRNA", "hiv-utr": "HIV-1 5' UTR RNA", "hiv-dis": "HIV dimerization RNA",
    "sars-cov-2": "SARS-CoV-2 RNA structure", "nanostructures": "RNA nanostructure",
    "tectorna": "tectoRNA self-assembly", "g-quadruplex": "RNA G-quadruplex",
}
# too generic to make a precise search term — don't seed combos from these methods.
_GENERIC = {"comput", "analytical-gel", "native-gel", "mutagenesis", "reporter-assay",
            "mass-spec", "rna-seq", "selex", "northern-blot"}


def _phrase(leaf: str) -> str:
    return _PHRASE.get(leaf, leaf.replace("-", " "))


def top_facet_combos(science_dir: Path, n: int = 6) -> list[tuple[str, str]]:
    """Most common DISTINCTIVE method×system pairs across your notes (drives Signal C).
    Skips over-generic methods so the keyword search stays on-topic."""
    from collections import Counter

    pairs: Counter = Counter()
    for md in science_dir.glob("*.md"):
        if md.name.startswith("MOC") or md.name.endswith(".fulltext.md"):
            continue
        t = md.read_text()
        methods = re.findall(r"(?m)^  - (method/\S+)", t.split("methods_used:", 1)[-1][:400]) if "methods_used:" in t else []
        systems = re.findall(r"(?m)^  - (system/\S+)", t.split("systems_used:", 1)[-1][:400]) if "systems_used:" in t else []
        for m in methods[:4]:
            ml = m.split("/")[1]
            if ml in _GENERIC:
                continue
            for s in systems[:4]:
                pairs[(ml, s.split("/")[1])] += 1
    return [pair for pair, _ in pairs.most_common(n)]


def facet_search(lib, combos: list[tuple[str, str]], per_combo: int = 15,
                 min_year: int = 2018) -> list[dict]:
    """Signal C: OpenAlex keyword search for your top method×system combos, not owned."""
    owned_dois, _ = _owned(lib)
    agg: dict[str, dict] = {}
    for method, system in combos:
        q = f"{_phrase(method)} {_phrase(system)}"
        # title+abstract search (not fulltext) keeps it on-topic; require RNA in scope.
        res = _oa_get("works",
                      filter=f"title_and_abstract.search:{q},from_publication_date:{min_year}-01-01",
                      select="id,doi,title,publication_year,cited_by_count,primary_location",
                      sort="cited_by_count:desc", per_page=per_combo)
        for w in (res or {}).get("results", []):
            wd = _clean_doi(w.get("doi"))
            if wd and wd in owned_dois:
                continue
            k = w["id"]
            if k not in agg:
                venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
                agg[k] = {"title": w.get("title") or "", "year": w.get("publication_year"),
                          "cites_n": w.get("cited_by_count", 0), "doi": wd, "venue": venue,
                          "combos": set()}
            agg[k]["combos"].add(f"{method} × {system}")
    out = [{**v, "combos": sorted(v["combos"])} for v in agg.values() if v["title"]]
    out.sort(key=lambda d: (-len(d["combos"]), -(d["cites_n"] or 0)))
    return out
