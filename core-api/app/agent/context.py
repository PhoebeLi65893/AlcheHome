import base64

MAX_TURNS = 20
MAX_CHARS = 4000
PHOTO_NOTE = "[photo attached]"
_ROLE = {"USER": "user", "HANDYMAN": "user", "BOT": "model"}


def _text_of(row) -> str:
    body = (row.body or "")[:MAX_CHARS]
    if getattr(row, "media_refs", None):
        return f"{body} {PHOTO_NOTE}".strip()
    return body


def build_contents(rows, images=(), max_turns: int = MAX_TURNS) -> list[dict]:
    """Turn stored messages (oldest first) into Gemini `contents`.

    Keeps the last `max_turns` messages, merges consecutive messages from the same role
    (Gemini expects alternating turns) and makes sure the list starts with the user.
    Earlier photos appear only as a text note; the bytes of `images` (the photos sent with
    the newest message, as (mime_type, bytes) pairs) are attached to the final user turn.
    """
    contents: list[dict] = []
    for row in list(rows)[-max_turns:]:
        role = _ROLE.get(row.sender, "user")
        text = _text_of(row)
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    if images and contents and contents[-1]["role"] == "user":
        for mime, data in images:
            contents[-1]["parts"].append(
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}
            )
    return contents
