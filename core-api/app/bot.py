from app import i18n


def reply_to(user_text: str, photos: int = 0, lang: str = "en") -> str:
    """Echo bot used when no Gemini key is set."""
    if not photos:
        return i18n.t(lang, "echo", text=user_text)
    if lang == "zh":
        note = i18n.t(lang, "echo_photos", n=photos)
    else:
        note = f"(received {photos} photo{'s' if photos > 1 else ''})"
    base = i18n.t(lang, "echo", text=user_text)
    return f"{base} {note}" if user_text else i18n.t(lang, "echo", text=note)
