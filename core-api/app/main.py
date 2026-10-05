import os
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import current_user
from app.auth import router as auth_router
from app.config import get_settings

app = FastAPI(title="Alche Home Core API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)


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
