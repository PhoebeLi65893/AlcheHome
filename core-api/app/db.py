import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import URL


def database_url() -> str:
    """DATABASE_URL wins. On Cloud Run, build a unix-socket URL from DB_* variables."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    password = os.getenv("DB_PASSWORD")
    instance = os.getenv("INSTANCE_CONNECTION_NAME")
    if password and instance:
        return URL.create(
            "postgresql+psycopg",
            username=os.getenv("DB_USER", "alche"),
            password=password,
            database=os.getenv("DB_NAME", "alche"),
            query={"host": f"/cloudsql/{instance}"},
        ).render_as_string(hide_password=False)
    return "postgresql+psycopg://alche:alche@localhost:5432/alche"


def get_engine():
    return create_engine(database_url(), pool_pre_ping=True)


@lru_cache
def shared_engine():
    """One pooled engine per process, used by the API."""
    return get_engine()
