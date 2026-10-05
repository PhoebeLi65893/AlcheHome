import os
from dataclasses import dataclass, field

DEV_JWT_SECRET = "dev-only-secret-change-me-dev-only-secret"


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    access_ttl_min: int
    refresh_ttl_days: int
    api_base_url: str
    web_base_url: str
    cors_origins: list[str] = field(default_factory=list)
    google_client_id: str = ""
    google_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""


def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "local")
    secret = os.getenv("JWT_SECRET") or ""
    if not secret:
        if env != "local":
            raise RuntimeError("JWT_SECRET must be set when APP_ENV is not 'local'")
        secret = DEV_JWT_SECRET
    web = (os.getenv("WEB_BASE_URL") or "http://localhost:3000").rstrip("/")
    return Settings(
        jwt_secret=secret,
        access_ttl_min=int(os.getenv("ACCESS_TTL_MIN") or 15),
        refresh_ttl_days=int(os.getenv("REFRESH_TTL_DAYS") or 30),
        api_base_url=(os.getenv("API_BASE_URL") or "http://localhost:8000").rstrip("/"),
        web_base_url=web,
        cors_origins=[web],
        google_client_id=os.getenv("GOOGLE_CLIENT_ID") or "",
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or "",
        facebook_app_id=os.getenv("FACEBOOK_APP_ID") or "",
        facebook_app_secret=os.getenv("FACEBOOK_APP_SECRET") or "",
    )
