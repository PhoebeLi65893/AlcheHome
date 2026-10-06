from dataclasses import dataclass

import httpx

from app.agent.prompt import SYSTEM_PROMPT
from app.config import get_settings

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    pass


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: dict


@dataclass(frozen=True)
class GeminiResult:
    text: str = ""
    function_call: FunctionCall | None = None


def generate(contents: list[dict], tools: list[dict] | None = None, note: str = "") -> GeminiResult:
    """Call the Gemini API (Google AI Studio key).

    `tools` are function declarations Gemini may call; `note` is extra context appended to the
    system instructions (for example, that a ticket already exists).
    """
    s = get_settings()
    system = SYSTEM_PROMPT + (f"\n\nCurrent situation: {note}" if note else "")
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    response = httpx.post(
        f"{BASE_URL}/models/{s.gemini_model}:generateContent",
        headers={"x-goog-api-key": s.gemini_api_key},
        json=payload,
        timeout=s.gemini_timeout_s,
    )
    if response.status_code >= 400:
        try:
            detail = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = response.text
        # Google's error text never contains the API key, so it is safe to log.
        raise GeminiError(f"HTTP {response.status_code}: {str(detail)[:300]}")
    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        parts = []
    texts, call = [], None
    for part in parts:
        if part.get("thought"):
            continue  # internal reasoning, never shown to the customer
        if "functionCall" in part and call is None:
            fc = part["functionCall"]
            call = FunctionCall(name=fc.get("name", ""), args=dict(fc.get("args") or {}))
        elif part.get("text"):
            texts.append(part["text"])
    text = "".join(texts).strip()
    if not text and call is None:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
        raise GeminiError(reason)
    return GeminiResult(text=text, function_call=call)
