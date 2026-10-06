import httpx

from app.agent.prompt import SYSTEM_PROMPT
from app.config import get_settings

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    pass


def generate(contents: list[dict]) -> str:
    """Call the Gemini API (Google AI Studio key) and return the reply text."""
    s = get_settings()
    response = httpx.post(
        f"{BASE_URL}/models/{s.gemini_model}:generateContent",
        headers={"x-goog-api-key": s.gemini_api_key},
        json={
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024},
        },
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
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
        raise GeminiError(reason)
    return text
