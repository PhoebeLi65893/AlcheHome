import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import current_user
from app.auth import router as auth_router
from app.channels.sms import router as sms_router
from app.chat import router as chat_router
from app.config import get_settings
from app.media import router as media_router
from app.tickets.router import router as tickets_router

# Show the app's own INFO logs (for example "SMS not sent ... not configured") in docker logs.
_log = logging.getLogger("app")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)

app = FastAPI(title="Alche Home Core API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(media_router)
app.include_router(tickets_router)
app.include_router(sms_router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "core-api",
        "version": app.version,
        "env": os.getenv("APP_ENV", "local"),
    }


@app.get("/me")
def me(user: Annotated[dict, Depends(current_user)]) -> dict:
    return {**user, "id": str(user["id"])}
