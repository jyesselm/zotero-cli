"""Vocabulary-constrained tag suggestion based on title and abstract content.

The approved controlled vocabulary in VOCABULARY is the single source of truth.
Suggestions are always a subset of it; the engine never invents a tag. When no
tag clears the confidence threshold, callers get an empty list and should fall
back to manual review (reading the abstract) rather than guessing.
"""

import re
from dataclasses import dataclass

from zotero_cli.models import ZoteroItem

# --- Approved controlled vocabulary (single source of truth) ----------------
VOCABULARY: frozenset[str] = frozenset(
    {
        # method/ - experimental & computational methods
        "method/chemical-mapping", "method/dms", "method/shape", "method/cryo-em",
        "method/xray", "method/nmr", "method/fret", "method/afm", "method/ml",
        "method/md", "method/comput", "method/single-molecule", "method/native-gel",
        "method/spr", "method/rna-map-array",
        # system/ - biological systems
        "system/ribosome", "system/spliceosome", "system/aptamer", "system/riboswitch",
        "system/ttr", "system/hammerhead", "system/nanostructures", "system/viral",
        "system/kink-turn", "system/tetra-ribozyme",
        # topic/ - research topics (thermodynamics has nested sub-tags)
        "topic/secondary-structure", "topic/tertiary-structure",
        "topic/structure-prediction", "topic/rna-design", "topic/rna-dynamics",
        "topic/thermodynamics", "topic/thermodynamics/tc",
        "topic/thermodynamics/mg-binding", "topic/thermodynamics/3d",
        "topic/thermodynamics/ion-effects", "topic/thermodynamics/ac-protonation",
        "topic/thermodynamics/rna-protonation", "topic/lab-automation",
        # type/ - paper category
        "type/review", "type/method", "type/my-paper", "type/benchmark", "type/book",
    }
)


@dataclass
class TagSuggestion:
    """A suggested tag with confidence score."""

    tag: str
    confidence: float
    reason: str


# Keyword patterns for tag suggestions. Every key MUST be in VOCABULARY (the
# module asserts this on import). Tags in VOCABULARY without patterns (e.g.
# type/my-paper, type/book, topic/thermodynamics/tc) can't be reliably detected
# from text and are intentionally left for manual review.
TAG_PATTERNS: dict[str, list[tuple[str, float]]] = {
    # --- methods: experimental ---
    "method/chemical-mapping": [
        (r"\b(chemical\s+mapping|chemical\s+probing|structure\s+probing)\b", 0.9),
        (r"\b(CMCT|hydroxyl\s+radical|in-line\s+probing)\b", 0.75),
    ],
    "method/dms": [
        (r"\bDMS(-MaPseq|-seq)?\b", 0.9),
        (r"\b(dimethyl\s+sulfate)\b", 0.9),
    ],
    "method/shape": [
        (r"\bSHAPE(-MaP|-seq)?\b", 0.9),
        (r"\b(2'-OH\s+acylation|selective\s+2.?-hydroxyl\s+acylation)\b", 0.9),
    ],
    "method/cryo-em": [
        (r"\b(cryo-?EM|cryo-?electron\s+microscopy|cryoEM)\b", 0.9),
        (r"\b(single.particle\s+(cryo|reconstruction)|tomography)\b", 0.6),
    ],
    "method/xray": [
        (r"\b(X-ray|crystal\s+structure|crystallograph(y|ic)|crystal\s+packing)\b", 0.85),
    ],
    "method/nmr": [
        (r"\bNMR\b", 0.9),
        (r"\b(nuclear\s+magnetic\s+resonance|NOESY|HSQC|chemical\s+shift)\b", 0.85),
    ],
    "method/fret": [
        (r"\b(smFRET|single.molecule\s+FRET)\b", 0.95),
        (r"\bFRET\b", 0.9),
        (r"\b(F.rster\s+resonance|fluorescence\s+resonance)\b", 0.85),
    ],
    "method/afm": [
        (r"\b(atomic\s+force\s+microscopy)\b", 0.9),
        (r"\bAFM\b", 0.85),
    ],
    "method/single-molecule": [
        (r"\b(single.molecule)\b", 0.9),
        (r"\b(optical\s+tweezers|magnetic\s+tweezers)\b", 0.85),
    ],
    "method/native-gel": [
        (r"\b(native\s+gel|native\s+PAGE|gel\s+electrophoresis)\b", 0.85),
    ],
    "method/spr": [
        (r"\b(surface\s+plasmon\s+resonance|SPR)\b", 0.85),
    ],
    "method/rna-map-array": [
        (r"\b(RNA-MaP|massively\s+parallel\s+(RNA\s+)?array|on-?array\s+RNA)\b", 0.85),
    ],
    # --- methods: computational ---
    "method/md": [
        (r"\b(molecular\s+dynamics|MD\s+simulation)\b", 0.9),
        (r"\b(AMBER|GROMACS|NAMD|OpenMM|force\s+field)\b", 0.8),
    ],
    "method/ml": [
        (r"\b(machine\s+learning|deep\s+learning|neural\s+network|language\s+model)\b", 0.9),
        (r"\b(CNN|RNN|transformer|LSTM|diffusion\s+model|generative\s+model)\b", 0.85),
        (r"\b(random\s+forest|gradient\s+boosting)\b", 0.8),
    ],
    "method/comput": [
        (r"\b(computational|in\s+silico|Monte\s+Carlo|algorithm|coarse.grained)\b", 0.7),
        (r"\b(simulation|computer\s+model|web\s+server|software\s+tool)\b", 0.65),
    ],
    # --- systems ---
    "system/ribosome": [
        (r"\bribosom\w*\b", 0.9),
        (r"\b(rRNA|ribosomal\s+RNA|23S|16S|28S|18S|peptidyl\s+transferase)\b", 0.8),
    ],
    "system/spliceosome": [
        (r"\bspliceosom\w*\b", 0.9),
        (r"\b(snRNA|snRNP|pre-mRNA\s+splicing)\b", 0.75),
        (r"\b(U1|U2|U4|U5|U6)\s*snRNA\b", 0.7),
    ],
    "system/ttr": [
        (r"\b(tetraloop.receptor|GAAA\s+tetraloop|11nt\s+receptor)\b", 0.95),
        (r"\b(tectoRNA|tecto-RNA)\b", 0.85),
    ],
    "system/tetra-ribozyme": [
        (r"\b(Tetrahymena\s+ribozyme|P4-?P6|group\s+I\s+(intron\s+)?ribozyme)\b", 0.9),
    ],
    "system/kink-turn": [
        (r"\b(kink.turn|k-turn|K-turn)\b", 0.95),
    ],
    "system/hammerhead": [
        (r"\bhammerhead\b", 0.9),
        (r"\b(HHRz|self.cleaving\s+ribozyme|twister(\s+sister)?\s+ribozyme)\b", 0.7),
    ],
    "system/aptamer": [
        (r"\baptamer\w*\b", 0.9),
        (r"\bSELEX\b", 0.8),
    ],
    "system/riboswitch": [
        (r"\briboswitch\w*\b", 0.95),
        (r"\b(aptamer\s+domain|expression\s+platform|RNA\s+thermometer)\b", 0.6),
    ],
    "system/nanostructures": [
        (r"\b(RNA\s+nanostructure|RNA\s+origami|DNA\s+origami|RNA\s+nanotechnology)\b", 0.95),
        (r"\b(nanocage|nanotube|self.assembl\w+\s+(RNA|DNA))\b", 0.7),
    ],
    "system/viral": [
        (r"\b(viral\s+RNA|virus|flavivir\w+|coronavirus)\b", 0.75),
        (r"\b(HIV|HCV|SARS|SARS-CoV-2|influenza|xrRNA)\b", 0.8),
    ],
    # --- topics ---
    "topic/secondary-structure": [
        (r"\b(secondary\s+structure|2D\s+structure|base.pair(ing)?)\b", 0.85),
        (r"\b(stem.loop|hairpin|pseudoknot)\b", 0.6),
    ],
    "topic/tertiary-structure": [
        (r"\b(tertiary\s+structure|3D\s+structure|tertiary\s+(fold|contact|interaction))\b", 0.9),
        (r"\b(long.range\s+interaction|3D\s+motif)\b", 0.8),
    ],
    "topic/structure-prediction": [
        (r"\b(structure\s+prediction|predict\w*\s+(secondary|tertiary|3D)\s+structure)\b", 0.9),
        (r"\b(RNA-Puzzles|inverse\s+fold\w*|fold\w*\s+prediction)\b", 0.8),
    ],
    "topic/rna-design": [
        (r"\b(RNA\s+design|sequence\s+design|de\s+novo\s+(RNA\s+)?design)\b", 0.9),
        (r"\b(EteRNA|Eterna|RNAinverse|NUPACK)\b", 0.8),
    ],
    "topic/rna-dynamics": [
        (r"\b(RNA\s+dynamics|conformational\s+(change|heterogeneity)|flexibilit\w+)\b", 0.85),
        (r"\b(structural\s+ensemble|multiple\s+conformation|folding\s+kinetics)\b", 0.7),
    ],
    "topic/thermodynamics": [
        (r"\b(thermodynamic|free\s+energy|enthalp\w+|entrop\w+)\b", 0.8),
        (r"\b(nearest.neighbor|binding\s+affinity|Kd|ITC|isothermal\s+titration)\b", 0.7),
    ],
    "topic/thermodynamics/mg-binding": [
        (r"\b(Mg2\+?|magnesium)\b.{0,40}\b(bind|fold|ion)\b", 0.85),
        (r"\b(Mg2\+?-?(binding|dependent)|magnesium\s+(binding|folding))\b", 0.9),
    ],
    "topic/thermodynamics/ion-effects": [
        (r"\b(ion\s+(effect|condition|atmosphere)|ionic\s+strength|salt\s+dependen)\b", 0.8),
        (r"\b(monovalent|divalent\s+cation|counterion)\b", 0.65),
    ],
    "topic/thermodynamics/ac-protonation": [
        (r"\b(A\+?[·.\-]?C|A-?C\s+(wobble|pair))\b.{0,30}\bproton", 0.85),
    ],
    "topic/thermodynamics/rna-protonation": [
        (r"\b(protonat\w+|pKa|protonated\s+(base|nucleotide))\b", 0.8),
    ],
    "topic/lab-automation": [
        (r"\b(liquid.handling\s+robot|pipetting\s+robot|Opentrons|lab\s+automation)\b", 0.9),
        (r"\b(automat\w+\s+(DNA\s+assembly|sample\s+prep)|design.build.test.learn|DBTL)\b", 0.8),
    ],
    # --- types ---
    "type/review": [
        (r"\breview\b", 0.7),
        (r"\b(perspective|overview|survey|we\s+(review|discuss|summarize))\b", 0.6),
    ],
    "type/method": [
        (r"\b(we\s+(developed|present|introduce)|new\s+(method|tool|software))\b", 0.7),
        (r"\b(protocol|pipeline|web\s+server|software\s+package)\b", 0.55),
    ],
    "type/benchmark": [
        (r"\b(benchmark\w*|comparison\s+of|critical\s+assessment|we\s+(compare|evaluate))\b", 0.75),
    ],
}

# Guarantee patterns never reference a tag outside the approved vocabulary.
_unknown = set(TAG_PATTERNS) - VOCABULARY
assert not _unknown, f"TAG_PATTERNS contains tags not in VOCABULARY: {sorted(_unknown)}"


def suggest_tags(item: ZoteroItem, existing_tags: list[str] | None = None) -> list[TagSuggestion]:
    """Suggest tags for an item based on title and abstract.

    Returns only tags from the approved VOCABULARY, sorted by confidence.
    An empty list means nothing matched confidently — read the abstract and
    tag manually rather than forcing a fit.
    """
    if existing_tags is None:
        existing_tags = []

    text = f"{item.title} {item.abstract}".lower()
    suggestions: list[TagSuggestion] = []

    for tag, patterns in TAG_PATTERNS.items():
        if tag in existing_tags:
            continue

        best_confidence = 0.0
        best_reason = ""
        for pattern, base_confidence in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                confidence = min(base_confidence + 0.05 * (len(matches) - 1), 0.99)
                if confidence > best_confidence:
                    best_confidence = confidence
                    match_text = matches[0] if isinstance(matches[0], str) else matches[0][0]
                    best_reason = f"matched '{match_text}'"

        if best_confidence >= 0.6:
            suggestions.append(
                TagSuggestion(tag=tag, confidence=best_confidence, reason=best_reason)
            )

    # Defensive: never emit anything outside the approved vocabulary.
    suggestions = [s for s in suggestions if s.tag in VOCABULARY]
    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions


def get_tag_categories() -> dict[str, list[str]]:
    """Get all tag categories and their tags from the approved vocabulary."""
    categories: dict[str, list[str]] = {}
    for tag in sorted(VOCABULARY):
        if "/" in tag:
            cat = tag.split("/")[0]
            categories.setdefault(cat, []).append(tag)
    return categories
