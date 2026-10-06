import pytest


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch):
    """Tests must never call the real Gemini API, even if a key is set in your shell."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
