import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import current_user
from app.auth import router as auth_router
from app.channels.sms import router as sms_router
from app.chat import router as chat_router
from app.config import get_settings
from app.dispatch import expire_overdue
from app.media import router as media_router
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


app = FastAPI(title="Alche Home Core API", version="0.8.0", lifespan=lifespan)

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
