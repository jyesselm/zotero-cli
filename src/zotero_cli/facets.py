"""Per-paper facets: "Methods used" + "Systems studied", richer than the coarse
method/*, system/* controlled tags.

Design (vetted, see LITNOTES.md §7): an agent extracts grounded specifics into a
`<slug>.facets.json` sidecar; this module VERIFIES each against the paper text and
NORMALIZES it to a canonical facet slug from a CLOSED vocabulary, then renders a
`zot:auto:facets` body region + `methods_used`/`systems_used` frontmatter arrays.

Separation of duties (the anti-hallucination + anti-sprawl core):
  * the agent proposes rich raw specifics + a hint; it never normalizes.
  * normalization is deterministic code here (alias map -> closed FACET_VOCAB);
    unmatched specifics go to a holding pen (kept in the body, kept OUT of the
    queryable frontmatter) until a human promotes them.
  * grounding is TERM-LEVEL against a hard-normalized fulltext (strips markdown
    escapes / Å / primes / respacing), so it survives the rendered reading note.

The sidecar is the single source of truth: both `zot litnote` and `zot relink`
re-render facets from it, so nothing is wiped on rebuild.
"""

from __future__ import annotations

import re

from zotero_cli.litnote import normalize, set_region

# --------------------------------------------------------------------------- #
# closed facet vocabulary (canonical slugs) — finer than suggest.VOCABULARY.
# Complements (never merges into) the authoritative coarse paper-tags.
# --------------------------------------------------------------------------- #
FACET_METHODS = {
    # chemical / enzymatic probing
    "method/dms", "method/dms-mapseq", "method/shape", "method/shape-mapseq",
    "method/chemical-mapping", "method/mutate-and-map", "method/mohca",
    "method/inline-probing", "method/hydroxyl-radical-footprinting",
    "method/rnase-footprinting", "method/dms-footprinting", "method/icshape",
    # structure determination
    "method/xray", "method/cryo-em", "method/cryo-et", "method/nmr", "method/saxs",
    "method/sans", "method/fret", "method/smfret",
    # biophysics / thermodynamics / kinetics
    "method/itc", "method/mst", "method/auc", "method/dsc", "method/spr",
    "method/stopped-flow", "method/optical-tweezers", "method/magnetic-tweezers",
    "method/uv-melting", "method/equilibrium-titration", "method/native-gel",
    "method/analytical-gel", "method/single-molecule",
    # sequencing / high-throughput
    "method/rna-seq", "method/selex", "method/deep-mutational-scanning",
    "method/rna-map-array", "method/hts-selection", "method/ribosome-profiling",
    "method/crosslinking-ms", "method/mass-spec",
    # computational
    "method/comput", "method/md", "method/ml", "method/structure-prediction",
    "method/rosetta-farfar", "method/docking", "method/qm",
}
FACET_SYSTEMS = {
    # tertiary motifs / small elements
    "system/ttr", "system/kink-turn", "system/pseudoknot", "system/g-quadruplex",
    "system/tetraloop", "system/a-minor", "system/three-way-junction",
    # ribozymes / introns / domains
    "system/tetra-ribozyme", "system/p4-p6", "system/group-i-intron",
    "system/group-ii-intron", "system/hammerhead", "system/hdv-ribozyme",
    "system/rnase-p", "system/hairpin-ribozyme", "system/glms-ribozyme",
    # riboswitches
    "system/riboswitch", "system/adenine-riboswitch", "system/purine-riboswitch",
    "system/sam-riboswitch", "system/b12-riboswitch", "system/tpp-riboswitch",
    "system/fmn-riboswitch", "system/tbox-riboswitch", "system/preq1-riboswitch",
    # aptamers
    "system/aptamer", "system/atp-aptamer", "system/spinach-aptamer",
    "system/broccoli-aptamer", "system/mango-aptamer", "system/malachite-green",
    # machines / large RNAs
    "system/ribosome", "system/rrna", "system/spliceosome", "system/snrna",
    "system/trna", "system/mrna", "system/srp",
    # viral
    "system/viral", "system/hiv-utr", "system/hiv-dis", "system/hiv-tar",
    "system/sars-cov-2", "system/hcv-ires", "system/ires",
    # designed
    "system/nanostructures", "system/tectorna",
}
FACET_VOCAB = frozenset(FACET_METHODS | FACET_SYSTEMS)

# raw-substring -> canonical. Matched longest-first against a normalized specific.
FACET_ALIASES: dict[str, str] = {
    # methods
    "dms-mapseq": "method/dms-mapseq", "dms mapseq": "method/dms-mapseq",
    "dimethyl sulfate mapping": "method/dms", "dms probing": "method/dms",
    "dms footprinting": "method/dms-footprinting", "dms": "method/dms",
    "shape-mapseq": "method/shape-mapseq", "shape-map": "method/shape-mapseq",
    "selective 2'-hydroxyl": "method/shape", "shape": "method/shape",
    "mutate-and-map": "method/mutate-and-map", "m2-seq": "method/mutate-and-map",
    "m2seq": "method/mutate-and-map", "in-line probing": "method/inline-probing",
    "inline probing": "method/inline-probing", "icshape": "method/icshape",
    "hydroxyl radical": "method/hydroxyl-radical-footprinting",
    "chemical mapping": "method/chemical-mapping", "chemical probing": "method/chemical-mapping",
    "enzymatic probing": "method/rnase-footprinting", "rnase v1": "method/rnase-footprinting",
    "x-ray crystallog": "method/xray", "crystal structure": "method/xray",
    "crystallography": "method/xray", "cryo-electron tomography": "method/cryo-et",
    "cryo-em": "method/cryo-em", "cryoem": "method/cryo-em", "cryo electron": "method/cryo-em",
    "nmr": "method/nmr", "nuclear magnetic resonance": "method/nmr",
    "small-angle x-ray": "method/saxs", "small angle x-ray": "method/saxs", "saxs": "method/saxs",
    "small-angle neutron": "method/sans", "sans": "method/sans",
    "single-molecule fret": "method/smfret", "single molecule fret": "method/smfret",
    "smfret": "method/smfret", "smfluorescence": "method/single-molecule",
    "single-molecule fluoresc": "method/single-molecule", "single molecule": "method/single-molecule",
    "forster resonance": "method/fret", "fret": "method/fret",
    "isothermal titration": "method/itc", "itc": "method/itc",
    "microscale thermophoresis": "method/mst", "mst": "method/mst",
    "analytical ultracentrifug": "method/auc", "sedimentation": "method/auc",
    "differential scanning calor": "method/dsc",
    "surface plasmon": "method/spr", "spr": "method/spr",
    "stopped-flow": "method/stopped-flow", "stopped flow": "method/stopped-flow",
    "optical tweezers": "method/optical-tweezers", "optical trap": "method/optical-tweezers",
    "magnetic tweezers": "method/magnetic-tweezers",
    "uv melting": "method/uv-melting", "uv-melting": "method/uv-melting",
    "melting curve": "method/uv-melting", "thermal denaturation": "method/uv-melting",
    "equilibrium titration": "method/equilibrium-titration",
    "mg2+ titration": "method/equilibrium-titration", "magnesium titration": "method/equilibrium-titration",
    "native gel": "method/native-gel", "native page": "method/native-gel",
    "gel electrophoresis": "method/analytical-gel", "gel-shift": "method/analytical-gel",
    "electrophoretic mobility": "method/analytical-gel",
    "rna-seq": "method/rna-seq", "rna sequencing": "method/rna-seq",
    "systematic evolution": "method/selex", "selex": "method/selex",
    "deep mutational": "method/deep-mutational-scanning",
    "ribosome profiling": "method/ribosome-profiling",
    "crosslinking mass spec": "method/crosslinking-ms", "xl-ms": "method/crosslinking-ms",
    "mass spectrometry": "method/mass-spec", "proteomics": "method/mass-spec",
    "molecular dynamics": "method/md", "md simulation": "method/md",
    "machine learning": "method/ml", "deep learning": "method/ml", "neural network": "method/ml",
    "structure prediction": "method/structure-prediction",
    "farfar": "method/rosetta-farfar", "rosetta": "method/rosetta-farfar",
    "molecular docking": "method/docking",
    "quantum mechanic": "method/qm", "dft": "method/qm", "ab initio": "method/qm",
    "computational": "method/comput",
    # systems
    "tetraloop-receptor": "system/ttr", "tetraloop receptor": "system/ttr",
    "gaaa tetraloop": "system/ttr", "tetraloop/receptor": "system/ttr", "ttr": "system/ttr",
    "kink-turn": "system/kink-turn", "kink turn": "system/kink-turn", "k-turn": "system/kink-turn",
    "pseudoknot": "system/pseudoknot", "g-quadruplex": "system/g-quadruplex",
    "quadruplex": "system/g-quadruplex", "a-minor": "system/a-minor",
    "three-way junction": "system/three-way-junction",
    "p4-p6": "system/p4-p6", "p4p6": "system/p4-p6",
    "tetrahymena": "system/tetra-ribozyme", "group i intron": "system/group-i-intron",
    "group ii intron": "system/group-ii-intron", "hammerhead": "system/hammerhead",
    "hdv ribozyme": "system/hdv-ribozyme", "hairpin ribozyme": "system/hairpin-ribozyme",
    "rnase p": "system/rnase-p", "glms": "system/glms-ribozyme",
    "adenine riboswitch": "system/adenine-riboswitch", "purine riboswitch": "system/purine-riboswitch",
    "sam riboswitch": "system/sam-riboswitch", "b12 riboswitch": "system/b12-riboswitch",
    "cobalamin riboswitch": "system/b12-riboswitch", "tpp riboswitch": "system/tpp-riboswitch",
    "fmn riboswitch": "system/fmn-riboswitch", "t-box": "system/tbox-riboswitch",
    "preq1": "system/preq1-riboswitch", "riboswitch": "system/riboswitch",
    "atp aptamer": "system/atp-aptamer", "spinach": "system/spinach-aptamer",
    "broccoli": "system/broccoli-aptamer", "mango aptamer": "system/mango-aptamer",
    "malachite green": "system/malachite-green", "aptamer": "system/aptamer",
    "large ribosomal subunit": "system/ribosome", "50s": "system/ribosome",
    "30s": "system/ribosome", "70s": "system/ribosome", "ribosom": "system/ribosome",
    "23s": "system/rrna", "16s": "system/rrna", "5s rrna": "system/rrna", "rrna": "system/rrna",
    "spliceosome": "system/spliceosome", "snrna": "system/snrna", "snrnp": "system/snrna",
    "trna": "system/trna", "transfer rna": "system/trna",
    "messenger rna": "system/mrna", "5'-utr": "system/mrna", "5' utr": "system/mrna",
    "signal recognition": "system/srp",
    "hiv-1 5'-utr": "system/hiv-utr", "hiv 5' utr": "system/hiv-utr",
    "dimerization initiation": "system/hiv-dis", "dis": "system/hiv-dis",
    "tar": "system/hiv-tar", "sars-cov-2": "system/sars-cov-2", "sars cov 2": "system/sars-cov-2",
    "hcv ires": "system/hcv-ires", "ires": "system/ires",
    "nanostructure": "system/nanostructures", "tecto-rna": "system/tectorna",
    "tectorna": "system/tectorna", "tectosquare": "system/tectorna",
    "viral rna": "system/viral", "viral genome": "system/viral",
}

# Anti-sprawl invariant (mirrors suggest.py's assert): every alias resolves into
# the closed vocab.
_unknown = set(FACET_ALIASES.values()) - FACET_VOCAB
assert not _unknown, f"FACET_ALIASES target(s) not in FACET_VOCAB: {sorted(_unknown)}"

_ALIAS_KEYS = sorted(FACET_ALIASES, key=len, reverse=True)  # longest-first match


# --------------------------------------------------------------------------- #
# grounding + normalization
# --------------------------------------------------------------------------- #
def ground_norm(s: str) -> str:
    """Hard-normalize for grounding: strip markdown escapes, ligatures/math-font
    (via litnote.normalize), Å/primes/dashes, case, and whitespace."""
    s = s.replace("\\", "")            # markdown-escape backslashes
    s = normalize(s)                   # ligatures, ð→( ¼→= control chars, etc.
    s = s.lower()
    for a, b in (("å", "a"), ("′", "'"), ("’", "'"), ("‐", "-"), ("–", "-"),
                 ("—", "-"), ("μ", "u"), ("×", "x")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def resolve(specific: str, hint: str | None) -> str | None:
    """Map a raw specific ('DMS-MaPseq (in-cell)') to a canonical facet slug, or
    None (holding pen). Alias substring match (longest-first), then a valid hint."""
    n = ground_norm(specific)
    for key in _ALIAS_KEYS:
        if key in n:
            return FACET_ALIASES[key]
    if hint and hint in FACET_VOCAB:
        return hint
    return None


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s)


def _grounded(term: str, detail: str | None, gtext: str, gsquash: str) -> tuple[bool, str | None]:
    """Term must appear in the grounded fulltext (plain or punctuation-squashed, so
    respacing/escapes don't false-drop). detail kept only if it also appears."""
    core_n = ground_norm(re.split(r"[(\[]", term)[0])  # drop parenthetical detail
    if len(core_n) < 3:
        return False, None
    # plain containment, or squashed (respacing/escape-tolerant) for terms long
    # enough that a squashed match is unlikely to be spurious.
    name_ok = core_n in gtext or (len(_squash(core_n)) >= 5 and _squash(core_n) in gsquash)
    kept = None
    if detail:
        dn = ground_norm(detail)
        if dn and (dn in gtext or _squash(dn) in gsquash):
            kept = detail.strip()
    return name_ok, kept


def _display(spec: str, detail: str | None) -> str:
    if not detail or detail.lower() in spec.lower():
        return spec
    name = re.split(r"[(\[]", spec)[0].strip()
    return f"{name} ({detail})"


# --------------------------------------------------------------------------- #
# process a sidecar against the fulltext  ->  a resolved facet set
# --------------------------------------------------------------------------- #
def process(sidecar: dict, fulltext: str) -> dict:
    """Verify + normalize a raw agent sidecar. Returns:
    {methods_used:[slug], systems_used:[slug],
     methods_display:[str], systems_display:[str],   # rich, for the body
     unresolved:[{specific,kind}], dropped:[{specific,kind}]}"""
    gtext = ground_norm(fulltext)
    gsquash = _squash(gtext)
    out = {"methods_used": [], "systems_used": [], "methods_display": [],
           "systems_display": [], "unresolved": [], "dropped": []}
    for kind, key_used, key_disp, prefix in (
        ("methods", "methods_used", "methods_display", "method/"),
        ("systems", "systems_used", "systems_display", "system/"),
    ):
        seen_slug, seen_disp = set(), set()
        for item in sidecar.get(kind, []):
            spec = (item.get("specific") or "").strip()
            if not spec:
                continue
            name_ok, detail = _grounded(spec, item.get("detail"), gtext, gsquash)
            if not name_ok:
                out["dropped"].append({"specific": spec, "kind": kind})
                continue
            disp = _display(spec, detail)
            if disp not in seen_disp:
                seen_disp.add(disp)
                out[key_disp].append(disp)
            slug = resolve(spec, item.get("facet_hint"))
            # a methods item must resolve to method/*, a systems item to system/* —
            # otherwise a stray alias in the wording would cross-contaminate the arrays.
            if slug is None or not slug.startswith(prefix):
                out["unresolved"].append({"specific": spec, "kind": kind})
            elif slug not in seen_slug:
                seen_slug.add(slug)
                out[key_used].append(slug)
        out[key_used].sort()
    return out


# --------------------------------------------------------------------------- #
# rendering — body region + scoped frontmatter (block-style, _read_frontmatter-safe)
# --------------------------------------------------------------------------- #
FIG_ANCHOR = "<!-- zot:auto:start:figures -->"


def facets_body(resolved: dict) -> str:
    """The zot:auto:facets managed region (rich display), or '' if nothing."""
    m, s = resolved["methods_display"], resolved["systems_display"]
    if not m and not s:
        return ""
    lines = ["<!-- zot:auto:start:facets -->", "## Methods & Systems"]
    if m:
        lines.append(f"**Methods:** {' · '.join(m)}")
    if s:
        lines.append(f"**Systems:** {' · '.join(s)}")
    if resolved["unresolved"]:
        u = ", ".join(x["specific"] for x in resolved["unresolved"][:8])
        lines.append(f"\n*Unclassified (awaiting vocab): {u}*")
    lines.append("<!-- zot:auto:end:facets -->")
    return "\n".join(lines)


def set_frontmatter_list(text: str, key: str, values: list[str]) -> str:
    """Insert/replace a block-style YAML list frontmatter key inside the --- fences.
    Removes the key if values is empty. Touches ONLY this key. Block-style keeps it
    parseable by litnote._read_frontmatter (which can't read inline `[a, b]`)."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    fm = text[3:end]      # "\n<frontmatter body>"
    rest = text[end:]     # "\n---\n<note body>"
    # drop any existing block-list form, then any inline form, for this key
    fm = re.sub(rf"(?m)^{re.escape(key)}:[ \t]*\n(?:[ \t]+-.*\n?)*", "", fm)
    fm = re.sub(rf"(?m)^{re.escape(key)}:.*\n?", "", fm)
    fm = fm.rstrip("\n")
    if values:
        fm += "\n" + f"{key}:\n" + "".join(f"  - {v}\n" for v in values)
    return "---" + fm.rstrip("\n") + rest


def apply_facets(text: str, resolved: dict) -> str:
    """Render facets into a note: body region (dedicated anchor, before figures) +
    methods_used/systems_used frontmatter. Idempotent; used by litnote AND relink."""
    text = set_region(text, "facets", facets_body(resolved), before=FIG_ANCHOR)
    text = set_frontmatter_list(text, "methods_used", resolved["methods_used"])
    text = set_frontmatter_list(text, "systems_used", resolved["systems_used"])
    return text
