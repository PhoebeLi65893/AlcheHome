def reply_to(user_text: str, photos: int = 0) -> str:
    """Echo bot used when no Gemini key is set."""
    if not photos:
        return f"Echo: {user_text}"
    note = f"(received {photos} photo{'s' if photos > 1 else ''})"
    return f"Echo: {user_text} {note}" if user_text else f"Echo: {note}"
