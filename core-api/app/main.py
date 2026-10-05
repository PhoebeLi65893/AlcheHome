import os

from fastapi import FastAPI

app = FastAPI(title="Alche Home Core API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "core-api",
        "version": app.version,
        "env": os.getenv("APP_ENV", "local"),
    }
