import pytest


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch):
    """Tests must never call the real Gemini API, even if a key is set in your shell."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def temp_media_dir(monkeypatch, tmp_path):
    """Uploaded photos go to a throwaway folder, never the real one."""
    monkeypatch.setenv("MEDIA_BACKEND", "local")
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    return tmp_path / "media"
