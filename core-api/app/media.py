import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import current_user
from app.config import get_settings
from app.db import shared_engine
from app.images import ImageRejected, process
from app.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])
User = Annotated[dict, Depends(current_user)]
CHUNK = 64 * 1024


class UploadOut(BaseModel):
    id: str
    mime_type: str
    size_bytes: int
    width: int
    height: int


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(CHUNK):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"Photo is larger than {limit // (1024 * 1024)} MB")
    return bytes(data)


@router.post("", response_model=UploadOut, status_code=201)
async def upload(file: UploadFile, user: User):
    raw = await _read_limited(file, get_settings().max_upload_bytes)
    try:
        jpeg, width, height = process(raw)
    except ImageRejected as e:
        raise HTTPException(415, str(e)) from None
    upload_id = uuid.uuid4()
    key = f"uploads/{user['id']}/{upload_id}.jpg"  # built server-side: never from the file name
    storage = get_storage()
    storage.save(key, jpeg, "image/jpeg")
    try:
        with shared_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO uploads (id, user_id, storage_key, mime_type, size_bytes, "
                    "width, height) VALUES (:i, :u, :k, 'image/jpeg', :s, :w, :h)"
                ),
                {
                    "i": upload_id,
                    "u": user["id"],
                    "k": key,
                    "s": len(jpeg),
                    "w": width,
                    "h": height,
                },
            )
    except Exception:
        storage.delete(key)
        raise
    return UploadOut(
        id=str(upload_id), mime_type="image/jpeg", size_bytes=len(jpeg), width=width, height=height
    )


def owned_uploads(conn, user_id, ids: list[uuid.UUID]):
    """Uploads with these ids that belong to the user, in the requested order."""
    if not ids:
        return []
    rows = conn.execute(
        text(
            "SELECT id, storage_key, mime_type FROM uploads "
            "WHERE id = ANY(:ids) AND user_id = :u"
        ),
        {"ids": list(ids), "u": user_id},
    ).all()
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


@router.get("/{upload_id}")
def download(upload_id: uuid.UUID, user: User):
    with shared_engine().connect() as conn:
        found = owned_uploads(conn, user["id"], [upload_id])
    if not found:
        raise HTTPException(404, "Photo not found")  # same answer for "missing" and "not yours"
    try:
        data = get_storage().load(found[0].storage_key)
    except (FileNotFoundError, OSError):
        logger.warning("Upload %s is in the database but missing from storage", upload_id)
        raise HTTPException(404, "Photo not found") from None
    return Response(
        data,
        media_type=found[0].mime_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
