"""Text the server itself writes (SMS, notices, replies) in English and Simplified Chinese.

Every function takes the *reader's* language. Anything not translated here falls back to
English, so a missing key never breaks a message.
"""

LANGS = ("en", "zh")
DEFAULT = "en"


def normalize(lang: str | None) -> str:
    return lang if lang in LANGS else DEFAULT


CATEGORY = {
    "en": {
        "PLUMBING": "Plumbing",
        "ELECTRICAL": "Electrical",
        "HVAC": "Heating / cooling",
        "CARPENTRY": "Carpentry",
        "APPLIANCE": "Appliance",
        "GENERAL": "General repair",
    },
    "zh": {
        "PLUMBING": "水管",
        "ELECTRICAL": "电工",
        "HVAC": "暖通空调",
        "CARPENTRY": "木工/地板",
        "APPLIANCE": "家电",
        "GENERAL": "综合维修",
    },
}

URGENCY = {
    "en": {"EMERGENCY": "Emergency", "SAME_DAY": "Today", "FLEXIBLE": "Flexible"},
    "zh": {"EMERGENCY": "紧急", "SAME_DAY": "今天", "FLEXIBLE": "时间灵活"},
}

WHEN = {  # inside a sentence
    "en": {"EMERGENCY": "emergency", "SAME_DAY": "today", "FLEXIBLE": "flexible timing"},
    "zh": {"EMERGENCY": "紧急", "SAME_DAY": "今天", "FLEXIBLE": "时间灵活"},
}

STR = {
    "en": {
        "offer": (
            "Alche Home job #{n}: {cat}, {when}, ZIP {zip}. {summary} Reply ACCEPT {n} to take it "
            "or DECLINE {n}. Expires in {mins}."
        ),
        "reminder": "Reminder, still open: ",
        "minutes": "{n} min",
        "hours": "{n} h",
        "help_offer": "To answer a job offer reply ACCEPT <number> or DECLINE <number>, e.g. ACCEPT 1024.",
        "job_gone": "Job #{n} is no longer available. Thanks for responding.",
        "job_gone_any": "That job is no longer available. Thanks for responding.",
        "several_offers": "More than one offer is open. Reply with the job number, e.g. ACCEPT 1024.",
        "passed_on": "No problem, we've passed job #{n} on.",
        "assigned_reply": (
            "Thanks! You're assigned to job #{n}. Text this number to message the customer "
            "(start with #{n} if you have several jobs)."
        ),
        "customer_accepted": (
            "Good news: {name} has accepted repair request #{n} ({cat}). "
            "You can message them from your request."
        ),
        "customer_assigned": (
            "Good news: {name} has been assigned to repair request #{n} ({cat}). "
            "You can message them from your request."
        ),
        "unmatched": (
            "We couldn't find an available handyman for request #{n} yet. "
            "Our team has been alerted and will follow up."
        ),
        "handyman_assigned_sms": (
            "Alche Home: you've been assigned job #{n} ({cat}, ZIP {zip}). We'll send the details next."
        ),
        "no_job": "You have no active job to message about. Reply ACCEPT <number> to take an offer.",
        "closed": "Job #{n} is no longer open for messages.",
        "several_jobs": "You have several jobs ({nums}). Start your message with the job number.",
        "write_after": "Write your message after the job number, e.g. #{n} on my way.",
        "to_handyman": "Job #{n} customer: {body}\n(Reply starting with #{n} to answer.)",
        "to_customer": "{name} ({cat}, request #{n}): {body}\nReply here to answer.",
        "code_sms": "Your Alche Home verification code is {code}",
        "new_request": "OK, starting a new request. What's the problem you need help with?",
        "sms_error": (
            "Sorry, something went wrong on our side. If this is an emergency, call 911. "
            "Otherwise please text us again in a moment."
        ),
        "lang_set": "OK, I'll reply in English.",
        "confirmation": (
            "I've created repair request #{n} ({cat}, {when}, ZIP {zip}). Next we'll look for an "
            "available handyman near you, and you'll be able to follow the status here."
        ),
        "already_has": (
            "This conversation already has repair request #{n}. To report a different problem, "
            "start a new request."
        ),
        "need_details": "Before I can create the request I still need ",
        "and": " and ",
        "fallback": (
            "Sorry, I'm having trouble right now. If this is an emergency (gas smell, fire, "
            "sparking wires), leave the area and call 911. Otherwise please try again in a moment."
        ),
        "no_ai_request": (
            "Creating a request from chat needs the AI assistant, which is not configured. "
            "For local testing type /ticket CATEGORY URGENCY ZIP description, for example: "
            "/ticket plumbing same_day 92101 Kitchen sink leaking under the cabinet"
        ),
        "pro_unavailable": (
            "The assistant is not configured yet (no GEMINI_API_KEY). Please try again later."
        ),
        "pro_fallback": "Sorry, the assistant is having trouble right now. Please try again in a moment.",
        "draft_fallback": (
            "Hi, this is {name} from Alche Home. I'll take care of your {cat} request (#{n}). "
            "When is a good time for me to come by?"
        ),
        "echo": "Echo: {text}",
        "echo_photos": "(received {n} photo(s))",
        "f_category": "the type of repair",
        "f_issue_summary": "a short description of the problem",
        "f_urgency": "how urgent it is",
        "f_location_zip": "a valid 5-digit ZIP code",
        "f_severity": "a severity level",
        "note_lang": "",
    },
    "zh": {
        "offer": (
            "Alche Home 工单 #{n}：{cat}，{when}，邮编 {zip}。{summary} 回复 ACCEPT {n} 接单，"
            "或回复 DECLINE {n} 拒绝。{mins}后过期。"
        ),
        "reminder": "提醒，此工单仍待处理：",
        "minutes": "{n} 分钟",
        "hours": "{n} 小时",
        "help_offer": "回复 ACCEPT <编号> 接单，或 DECLINE <编号> 拒绝，例如 ACCEPT 1024。",
        "job_gone": "工单 #{n} 已不可接。感谢你的回复。",
        "job_gone_any": "该工单已不可接。感谢你的回复。",
        "several_offers": "你有多个待处理的工单。请带上工单编号回复，例如 ACCEPT 1024。",
        "passed_on": "好的，工单 #{n} 已转给其他师傅。",
        "assigned_reply": (
            "谢谢！工单 #{n} 已分配给你。直接回复此号码即可联系客户（如果有多个工单，"
            "请以 #{n} 开头）。"
        ),
        "customer_accepted": "好消息：{name} 已接受维修请求 #{n}（{cat}）。你可以在请求里给他发消息。",
        "customer_assigned": "好消息：已为维修请求 #{n}（{cat}）安排 {name}。你可以在请求里给他发消息。",
        "unmatched": "暂时没有找到可接单的师傅（请求 #{n}）。我们的团队已收到提醒，会尽快跟进。",
        "handyman_assigned_sms": "Alche Home：你已被分配工单 #{n}（{cat}，邮编 {zip}）。详细信息稍后发送。",
        "no_job": "你目前没有可发消息的进行中工单。回复 ACCEPT <编号> 来接单。",
        "closed": "工单 #{n} 已关闭，无法再发消息。",
        "several_jobs": "你有多个工单（{nums}）。请在消息开头写上工单编号。",
        "write_after": "请在工单编号后面写消息，例如：#{n} 我快到了。",
        "to_handyman": "工单 #{n} 客户：{body}\n（回复请以 #{n} 开头。）",
        "to_customer": "{name}（{cat}，请求 #{n}）：{body}\n直接回复即可。",
        "code_sms": "你的 Alche Home 验证码是 {code}",
        "new_request": "好的，开始新的请求。你需要解决什么问题？",
        "sms_error": "抱歉，我们这边出了点问题。如果是紧急情况，请拨打 911。否则请稍后再发短信给我们。",
        "lang_set": "好的，我会用中文回复。",
        "confirmation": (
            "我已创建维修请求 #{n}（{cat}，{when}，邮编 {zip}）。接下来我们会为你寻找附近可接单的师傅，"
            "你可以在这里查看进度。"
        ),
        "already_has": "此对话已有维修请求 #{n}。如需报告另一个问题，请开始新的请求。",
        "need_details": "创建请求之前，我还需要",
        "and": "和",
        "fallback": (
            "抱歉，我现在遇到了问题。如果是紧急情况（闻到煤气味、起火、电线冒火花），请立即离开现场并"
            "拨打 911。否则请稍后再试。"
        ),
        "no_ai_request": (
            "通过聊天创建请求需要 AI 助手，但目前未配置。本地测试可输入 "
            "/ticket 类别 紧急程度 邮编 描述，例如：/ticket plumbing same_day 92101 厨房水槽漏水"
        ),
        "pro_unavailable": "助手尚未配置（缺少 GEMINI_API_KEY），请稍后再试。",
        "pro_fallback": "抱歉，助手现在遇到了问题，请稍后再试。",
        "draft_fallback": "你好，我是 Alche Home 的 {name}。我会处理你的{cat}请求（#{n}），请问什么时候方便我上门？",
        "echo": "回声：{text}",
        "echo_photos": "（收到 {n} 张照片）",
        "f_category": "维修类型",
        "f_issue_summary": "对问题的简短描述",
        "f_urgency": "紧急程度",
        "f_location_zip": "有效的 5 位邮编",
        "f_severity": "严重程度",
        "note_lang": "Reply to the user in Simplified Chinese (简体中文).",
    },
}


def t(lang: str | None, key: str, **kw) -> str:
    table = STR[normalize(lang)]
    s = table.get(key)
    if s is None:
        s = STR[DEFAULT][key]
    return s.format(**kw) if kw else s


def category(lang: str | None, code: str) -> str:
    return CATEGORY[normalize(lang)].get(code, CATEGORY[DEFAULT].get(code, code))


def urgency(lang: str | None, code: str) -> str:
    return URGENCY[normalize(lang)].get(code, code)


def when(lang: str | None, code: str) -> str:
    return WHEN[normalize(lang)].get(code, code)


def duration(lang: str | None, seconds: float) -> str:
    m = round(seconds / 60)
    return t(lang, "minutes", n=m) if m < 120 else t(lang, "hours", n=round(m / 60))
