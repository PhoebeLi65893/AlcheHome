import pytest

from app.storage import LocalStorage, get_storage


def test_local_storage_roundtrip_and_delete(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.save("uploads/u1/a.jpg", b"data", "image/jpeg")
    assert s.load("uploads/u1/a.jpg") == b"data"
    s.delete("uploads/u1/a.jpg")
    with pytest.raises(FileNotFoundError):
        s.load("uploads/u1/a.jpg")


@pytest.mark.parametrize("key", ["../outside.jpg", "uploads/../../x", "/etc/passwd"])
def test_local_storage_refuses_keys_outside_its_folder(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStorage(str(tmp_path / "root")).save(key, b"x", "image/jpeg")


def test_gcs_backend_requires_a_bucket(monkeypatch):
    monkeypatch.setenv("MEDIA_BACKEND", "gcs")
    monkeypatch.delenv("MEDIA_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="MEDIA_BUCKET"):
        get_storage()
