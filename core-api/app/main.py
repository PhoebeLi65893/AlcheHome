import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.admin import router as admin_router
from app.auth import current_user
from app.auth import router as auth_router
from app.channels.sms import router as sms_router
from app.chat import router as chat_router
from app.config import get_settings
from app.db import shared_engine
from app.dispatch import expire_overdue, remind_unanswered
from app.media import router as media_router
from app.pro import router as pro_router
from app.profile import admin_router as handymen_admin_router
from app.profile import customer_router as customer_profile_router
from app.profile import router as profile_router
from app.threads import router as threads_router
from app.tickets.router import router as tickets_router

# Show the app's own INFO logs (for example "SMS not sent ... not configured") in docker logs.
_log = logging.getLogger("app")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)

SWEEP_SECONDS = 10


async def _sweep_offers() -> None:
    """Roll timed-out job offers to the next handyman."""
    while True:
        await asyncio.sleep(SWEEP_SECONDS)
        try:
            await asyncio.to_thread(expire_overdue)
            await asyncio.to_thread(remind_unanswered)
        except Exception:
            _log.exception("Offer timeout sweep failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = (
        asyncio.create_task(_sweep_offers()) if os.getenv("DISPATCH_WORKER", "1") != "0" else None
    )
    yield
    if task:
        task.cancel()


app = FastAPI(title="Alche Home Core API", version="0.17.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(media_router)
app.include_router(tickets_router)
app.include_router(sms_router)
app.include_router(admin_router)
app.include_router(pro_router)
app.include_router(profile_router)
app.include_router(customer_profile_router)
app.include_router(handymen_admin_router)
app.include_router(threads_router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "core-api",
        "version": app.version,
        "env": os.getenv("APP_ENV", "local"),
        "revision": os.getenv("K_REVISION", ""),  # the Cloud Run revision, set by Google
    }


@app.get("/me")
def me(user: Annotated[dict, Depends(current_user)]) -> dict:
    return {**user, "id": str(user["id"])}


class LanguageIn(BaseModel):
    language: Literal["en", "zh"]


@app.put("/me/language")
def set_language(body: LanguageIn, user: Annotated[dict, Depends(current_user)]) -> dict:
    """The language of this account's screens, texts and AI replies (English or Chinese)."""
    with shared_engine().begin() as conn:
        conn.execute(
            text("UPDATE users SET language = :l WHERE id = :u"),
            {"l": body.language, "u": user["id"]},
        )
    return {"language": body.language}
