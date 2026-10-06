"""Safety layer: deterministic emergency detection that runs BEFORE any AI call.

It deliberately errs on the side of caution: a false alarm costs the user one extra
message, a missed gas leak could cost a life. It never depends on the model.
"""

import re

_GAP = r"[^.?!]{0,25}"
_ELECTRIC = r"(?:outlets?|panel|breaker(?: box)?|fuse box|wires?|wiring|sockets?|switch|cord)"
_WIDE = r"[^.?!]{0,80}"  # water can be described far from the electrical part in a sentence
_LIVE_PARTS = r"(?:outlets?|electrical panel|breaker box|fuse box|light fixture)"
_BUILDING = r"(?:ceiling|floor|roof|wall|deck|balcony)"
_COLLAPSE = r"(?:collaps\w*|caving in|caved in|giving way)"

_PATTERNS: dict[str, list[str]] = {
    "gas": [
        rf"\b(?:smell|smells|smelled|smelling|odou?r)\b{_GAP}\bgas\b",
        r"\bgas\b[^.?!]{0,20}\b(?:leak|leaks|leaking|smell|smells|odou?r)\b",
        r"\brotten eggs?\b",
    ],
    "carbon_monoxide": [
        r"\bcarbon monoxide\b",
        r"\bco\b[^.?!]{0,12}\b(?:alarm|detector|poisoning)\b",
    ],
    "fire": [
        r"\b(?:on|caught|catching) fire\b",
        r"\b(?:house|kitchen|electrical|wall|attic|roof|garage) fire\b",
        r"\b(?:see|saw|seeing)\b[^.?!]{0,15}\b(?:flames?|smoke|fire)\b",
        rf"\bsmoke\b{_GAP}\b{_ELECTRIC}\b",
        rf"\b{_ELECTRIC}\b{_GAP}\bsmok(?:e|ing)\b",
        r"\bsmoke (?:is )?(?:coming|pouring)\b",
    ],
    "electrical": [
        rf"\bsparks?\b[^.?!]{{0,30}}\b{_ELECTRIC}\b",
        rf"\b{_ELECTRIC}\b[^.?!]{{0,30}}\b(?:spark|sparks|sparked|sparking)\b",
        rf"\bburning smell\b[^.?!]{{0,30}}\b{_ELECTRIC}\b",
        rf"\b{_ELECTRIC}\b[^.?!]{{0,30}}\bburning smell\b",
        r"\b(?:electric(?:al)? shock|got shocked|shocked me|electrocut\w*)\b",
    ],
    "flood_electric": [
        rf"\b(?:water|flood\w*|leak\w*)\b{_WIDE}\b{_LIVE_PARTS}\b",
        rf"\b{_LIVE_PARTS}\b{_WIDE}\b(?:water|wet|flood\w*|dripping)\b",
    ],
    "structural": [
        rf"\b{_BUILDING}\b[^.?!]{{0,20}}\b{_COLLAPSE}\b",
        rf"\b{_COLLAPSE}\b[^.?!]{{0,20}}\b{_BUILDING}\b",
    ],
}
_COMPILED = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in _PATTERNS.items()}

_TAIL = (
    " I'm an automated assistant and can't call emergency services for you. "
    "Once everyone is safe, I'm happy to help you arrange the repair."
)

EMERGENCY_REPLIES = {
    "gas": (
        "This could be a gas leak, which is dangerous. Please act now: 1) Leave the building "
        "immediately with everyone inside. 2) Don't use light switches, appliances, lighters or "
        "your phone until you are outside. 3) From outside, call 911 and your gas company's "
        "emergency line. Don't go back in until responders say it's safe." + _TAIL
    ),
    "carbon_monoxide": (
        "A carbon monoxide alarm is serious. Get everyone, including pets, outside into fresh "
        "air right now and call 911. Don't go back in until responders say it's safe, even if "
        "the alarm stops." + _TAIL
    ),
    "fire": (
        "Fire or smoke is an emergency. Get everyone out now, close doors behind you if you "
        "can, and call 911 from outside. Don't try to fight a spreading fire and don't go back "
        "inside for belongings." + _TAIL
    ),
    "electrical": (
        "Sparking, burning smells or shocks from electrical equipment can start a fire. Stay "
        "away from it and don't touch it. If you see smoke or flames, or anyone was shocked, "
        "leave and call 911 now. Never use water on an electrical fire. If the main breaker is "
        "dry and easy to reach you may switch it off; otherwise stay back." + _TAIL
    ),
    "flood_electric": (
        "Water near electrical outlets, panels or fixtures is a shock and fire risk. Don't "
        "touch them or step into standing water near them. Keep everyone away, and if you "
        "can't do that safely, leave and call 911. If the main breaker is dry and easy to "
        "reach you may switch it off." + _TAIL
    ),
    "structural": (
        "A collapsing ceiling, floor or wall is dangerous. Move everyone away from that area "
        "and outside if you can, then call 911. Don't go back near it until it has been "
        "inspected." + _TAIL
    ),
}


def check_emergency(text: str) -> str | None:
    """Return the emergency category for a user message, or None."""
    normalized = " ".join(text.split())
    for category, patterns in _COMPILED.items():
        if any(p.search(normalized) for p in patterns):
            return category
    return None
