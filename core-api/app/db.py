import os

from sqlalchemy import create_engine


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+psycopg://alche:alche@localhost:5432/alche")


def get_engine():
    return create_engine(database_url(), pool_pre_ping=True)
