"""Smart tag suggestion based on title and abstract content."""

import re
from dataclasses import dataclass

from zotero_cli.models import ZoteroItem


@dataclass
class TagSuggestion:
    """A suggested tag with confidence score."""

    tag: str
    confidence: float
    reason: str


# Keyword patterns for tag suggestions
TAG_PATTERNS: dict[str, list[tuple[str, float]]] = {
    # Methods - experimental
    "method/chemical-mapping": [
        (r"\b(chemical\s+mapping|chemical\s+probing)\b", 0.9),
        (r"\b(SHAPE|DMS|CMCT|hydroxyl\s+radical)\b", 0.8),
    ],
    "method/dms": [
        (r"\bDMS\b", 0.9),
        (r"\b(dimethyl\s+sulfate)\b", 0.9),
    ],
    "method/shape": [
        (r"\bSHAPE\b", 0.9),
        (r"\b(2'-OH\s+acylation|SHAPE-MaP|SHAPE-seq)\b", 0.9),
    ],
    "method/cryo-em": [
        (r"\b(cryo-?EM|cryo-?electron\s+microscopy|cryoEM)\b", 0.9),
        (r"\b(single.particle|tomography)\b", 0.6),
    ],
    "method/xray": [
        (r"\b(X-ray|x-ray|crystal\s+structure|crystallography)\b", 0.85),
    ],
    "method/nmr": [
        (r"\bNMR\b", 0.9),
        (r"\b(nuclear\s+magnetic\s+resonance|NOESY|HSQC)\b", 0.9),
    ],
    "method/fret": [
        (r"\bFRET\b", 0.9),
        (r"\b(F.rster|fluorescence\s+resonance)\b", 0.85),
        (r"\b(smFRET|single.molecule\s+FRET)\b", 0.95),
    ],
    "method/afm": [
        (r"\bAFM\b", 0.85),
        (r"\b(atomic\s+force\s+microscopy)\b", 0.9),
    ],
    "method/single-molecule": [
        (r"\b(single.molecule|single-molecule)\b", 0.9),
        (r"\b(optical\s+tweezers|magnetic\s+tweezers)\b", 0.85),
    ],
    "method/native-gel": [
        (r"\b(native\s+gel|native\s+PAGE|gel\s+electrophoresis)\b", 0.85),
    ],
    # Methods - computational
    "method/comput": [
        (r"\b(computational|simulation|molecular\s+dynamics|MD)\b", 0.7),
        (r"\b(in\s+silico|computer\s+model)\b", 0.75),
    ],
    "method/ml": [
        (r"\b(machine\s+learning|deep\s+learning|neural\s+network)\b", 0.9),
        (r"\b(CNN|RNN|transformer|LSTM)\b", 0.85),
        (r"\b(random\s+forest|gradient\s+boosting)\b", 0.8),
    ],
    "method/md": [
        (r"\b(molecular\s+dynamics|MD\s+simulation)\b", 0.9),
        (r"\b(AMBER|GROMACS|NAMD|OpenMM)\b", 0.85),
    ],
    # Systems
    "system/ribosome": [
        (r"\bribosom\w*\b", 0.9),
        (r"\b(rRNA|ribosomal\s+RNA|23S|16S|28S|18S)\b", 0.85),
        (r"\b(translation|peptidyl\s+transferase)\b", 0.6),
    ],
    "system/splicesome": [
        (r"\bspliceosom\w*\b", 0.9),
        (r"\b(snRNA|snRNP|splicing)\b", 0.75),
        (r"\b(U1|U2|U4|U5|U6)\s*(snRNA)?\b", 0.7),
    ],
    "system/ttr": [
        (r"\b(tetraloop.receptor|GAAA.tetraloop|11nt\s+receptor)\b", 0.95),
        (r"\b(tectoRNA|tecto-RNA)\b", 0.85),
    ],
    "system/kink-turn": [
        (r"\b(kink.turn|k-turn|K-turn)\b", 0.95),
    ],
    "system/hammerhead": [
        (r"\bhammerhead\b", 0.9),
        (r"\b(HHRz|self.cleaving)\b", 0.7),
    ],
    "system/aptamer": [
        (r"\baptamer\w*\b", 0.9),
        (r"\bSELEX\b", 0.8),
    ],
    "system/riboswitch": [
        (r"\briboswitch\w*\b", 0.95),
        (r"\b(aptamer\s+domain|expression\s+platform)\b", 0.6),
    ],
    "system/nanostructures": [
        (r"\b(RNA\s+nanostructure|RNA\s+origami|RNA\s+nanotechnology)\b", 0.95),
        (r"\b(nanoparticle|self.assembl)\b", 0.6),
    ],
    "system/viral": [
        (r"\b(viral\s+RNA|virus)\b", 0.75),
        (r"\b(HIV|HCV|SARS|coronavirus|influenza)\b", 0.8),
    ],
    # Topics
    "topic/secondary-structure": [
        (r"\b(secondary\s+structure|2D\s+structure|base.pair)\b", 0.85),
        (r"\b(stem.loop|hairpin|helix)\b", 0.6),
    ],
    "topic/tertiary-structure": [
        (r"\b(tertiary\s+structure|3D\s+structure|tertiary\s+fold)\b", 0.9),
        (r"\b(tertiary\s+contact|long.range\s+interaction)\b", 0.85),
    ],
    "topic/thermodynamics": [
        (r"\b(thermodynamic|free\s+energy|enthalpy|entropy)\b", 0.85),
        (r"\b(\u0394G|\u0394H|Kd|binding\s+affinity)\b", 0.8),
        (r"\b(nearest.neighbor|NN\s+parameter)\b", 0.9),
    ],
    "topic/rna-design": [
        (r"\b(RNA\s+design|sequence\s+design|inverse\s+fold)\b", 0.95),
        (r"\b(RNAinverse|Rosetta|NUPACK)\b", 0.8),
    ],
    "topic/rna-flexibility": [
        (r"\b(RNA\s+dynamics|conformational\s+change|flexibility)\b", 0.85),
        (r"\b(ensemble|multiple\s+conformation)\b", 0.6),
    ],
    "topic/deep-learning": [
        (r"\b(deep\s+learning|neural\s+network|CNN|transformer)\b", 0.9),
    ],
    # Types
    "type/review": [
        (r"\breview\b", 0.7),
        (r"\b(perspective|overview|survey)\b", 0.6),
    ],
    "type/method": [
        (r"\b(method|protocol|pipeline|workflow)\b", 0.5),
        (r"\b(we\s+developed|we\s+present|new\s+method)\b", 0.7),
    ],
    "type/benchmark": [
        (r"\b(benchmark|comparison|evaluation|assessment)\b", 0.7),
        (r"\b(performance|accuracy|precision|recall)\b", 0.5),
    ],
}


def suggest_tags(item: ZoteroItem, existing_tags: list[str] | None = None) -> list[TagSuggestion]:
    """Suggest tags for an item based on title and abstract."""
    if existing_tags is None:
        existing_tags = []

    text = f"{item.title} {item.abstract}".lower()
    suggestions: list[TagSuggestion] = []

    for tag, patterns in TAG_PATTERNS.items():
        # Skip if already tagged
        if tag in existing_tags:
            continue

        best_confidence = 0.0
        best_reason = ""

        for pattern, base_confidence in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Boost confidence if multiple matches
                confidence = min(base_confidence + 0.05 * (len(matches) - 1), 0.99)
                if confidence > best_confidence:
                    best_confidence = confidence
                    # Get first match as reason
                    match_text = matches[0] if isinstance(matches[0], str) else matches[0][0]
                    best_reason = f"matched '{match_text}'"

        if best_confidence >= 0.6:
            suggestions.append(
                TagSuggestion(tag=tag, confidence=best_confidence, reason=best_reason)
            )

    # Sort by confidence
    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions


def get_tag_categories() -> dict[str, list[str]]:
    """Get all tag categories and their tags."""
    categories: dict[str, list[str]] = {}
    for tag in TAG_PATTERNS.keys():
        if "/" in tag:
            cat = tag.split("/")[0]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(tag)
    return categories
