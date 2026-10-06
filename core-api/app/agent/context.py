MAX_TURNS = 20
MAX_CHARS = 4000
_ROLE = {"USER": "user", "HANDYMAN": "user", "BOT": "model"}


def build_contents(rows, max_turns: int = MAX_TURNS) -> list[dict]:
    """Turn stored messages (oldest first) into Gemini `contents`.

    Keeps the last `max_turns` messages, merges consecutive messages from the same
    role (Gemini expects alternating turns) and makes sure the list starts with the user.
    """
    contents: list[dict] = []
    for row in list(rows)[-max_turns:]:
        role = _ROLE.get(row.sender, "user")
        text = row.body[:MAX_CHARS]
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    return contents
