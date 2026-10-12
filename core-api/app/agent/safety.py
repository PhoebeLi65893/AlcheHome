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


# Chinese: the same categories, so a Chinese-speaking customer gets the same protection.
_ZH = "[^。！？!?]"
_PATTERNS_ZH: dict[str, list[str]] = {
    "gas": [
        rf"(?:煤气|燃气|天然气|瓦斯){_ZH}{{0,10}}(?:泄漏|泄露|漏气|味|臭)",
        rf"闻到{_ZH}{{0,6}}(?:煤气|燃气|天然气|瓦斯)",
        r"漏气|煤气味",
    ],
    "carbon_monoxide": [r"一氧化碳"],
    "fire": [r"着火|起火|失火|火灾|冒烟|冒火|烧起来|明火"],
    "electrical": [
        r"触电|电击|漏电|被电到",
        rf"(?:插座|电线|线路|电路|配电箱|电箱|开关){_ZH}{{0,10}}(?:火花|打火|冒烟|烧焦|焦味|糊味)",
    ],
    "flood_electric": [
        rf"(?:漏水|进水|积水|水){_ZH}{{0,20}}(?:插座|配电箱|电箱|电表|开关|灯)",
        rf"(?:插座|配电箱|电箱|开关){_ZH}{{0,20}}(?:进水|漏水|有水|泡水|湿)",
    ],
    "structural": [rf"(?:天花板|屋顶|房顶|地板|墙){_ZH}{{0,10}}(?:坍塌|倒塌|塌|垮)"],
}
_COMPILED_ZH = {k: [re.compile(p) for p in v] for k, v in _PATTERNS_ZH.items()}

EMERGENCY_REPLIES_ZH = {
    "gas": (
        "这可能是煤气泄漏，非常危险。请立即行动：1）马上带着屋内所有人离开建筑。2）在走到室外之前，"
        "不要开关灯、使用电器、打火机或手机。3）到室外后拨打 911，并联系燃气公司的紧急电话。"
        "在救援人员确认安全之前不要返回。"
    ),
    "carbon_monoxide": (
        "一氧化碳报警很严重。请立即带所有人（包括宠物）到室外呼吸新鲜空气并拨打 911。"
        "即使警报停止，也要等救援人员确认安全后再返回。"
    ),
    "fire": (
        "起火或冒烟属于紧急情况。请立刻让所有人撤离，离开时尽量关上身后的门，并在室外拨打 911。"
        "不要试图扑灭蔓延的火势，也不要为了拿东西返回室内。"
    ),
    "electrical": (
        "电气设备冒火花、有焦糊味或触电可能引发火灾。请远离且不要触碰。如果看到烟或火焰，"
        "或有人触电，请立即离开并拨打 911。切勿用水扑灭电气火灾。如果总开关干燥且容易够到，"
        "可以关闭总开关；否则请保持距离。"
    ),
    "flood_electric": (
        "插座、配电箱或灯具附近有水会带来触电和火灾风险。不要触碰，也不要踩进它们附近的积水。"
        "让所有人远离；如果无法安全做到，请离开并拨打 911。如果总开关干燥且容易够到，可以关闭它。"
    ),
    "structural": (
        "天花板、地板或墙体坍塌非常危险。请让所有人远离该区域，尽可能到室外，然后拨打 911。"
        "在检查确认安全之前不要靠近。"
    ),
}
_TAIL_ZH = "我是自动助手，无法替你呼叫紧急服务。等大家都安全之后，我很乐意帮你安排维修。"


def emergency_reply(category: str, lang: str = "en") -> str:
    if lang == "zh":
        return EMERGENCY_REPLIES_ZH[category] + " " + _TAIL_ZH
    return EMERGENCY_REPLIES[category]


def check_emergency(text: str) -> str | None:
    """Return the emergency category for a user message, or None."""
    normalized = " ".join(text.split())
    for compiled in (_COMPILED, _COMPILED_ZH):
        for category, patterns in compiled.items():
            if any(p.search(normalized) for p in patterns):
                return category
    return None
