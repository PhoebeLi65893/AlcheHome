"""Where photo bytes live: a local folder for development, Cloud Storage in the cloud."""

from functools import lru_cache
from pathlib import Path

from app.config import get_settings


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class GCSStorage:
    def __init__(self, bucket: str):
        self.bucket = _gcs_bucket(bucket)

    def save(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def load(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()

    def delete(self, key: str) -> None:
        self.bucket.blob(key).delete()


@lru_cache
def _gcs_bucket(name: str):
    from google.cloud import storage  # imported lazily: only needed in the cloud

    return storage.Client().bucket(name)


def get_storage():
    s = get_settings()
    if s.media_backend == "gcs":
        if not s.media_bucket:
            raise RuntimeError("MEDIA_BUCKET must be set when MEDIA_BACKEND=gcs")
        return GCSStorage(s.media_bucket)
    return LocalStorage(s.media_dir)
