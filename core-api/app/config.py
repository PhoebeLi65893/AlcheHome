import os
from dataclasses import dataclass, field

DEV_JWT_SECRET = "dev-only-secret-change-me-dev-only-secret"


@dataclass(frozen=True)
class Settings:
    app_env: str
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
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_timeout_s: float = 20.0
    media_backend: str = "local"
    media_dir: str = "./media-data"
    media_bucket: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024


def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "local")
    secret = os.getenv("JWT_SECRET") or ""
    if not secret:
        if env != "local":
            raise RuntimeError("JWT_SECRET must be set when APP_ENV is not 'local'")
        secret = DEV_JWT_SECRET
    web = (os.getenv("WEB_BASE_URL") or "http://localhost:3000").rstrip("/")
    return Settings(
        app_env=env,
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
        gemini_api_key=os.getenv("GEMINI_API_KEY") or "",
        gemini_model=os.getenv("GEMINI_MODEL") or "gemini-3.5-flash",
        gemini_timeout_s=float(os.getenv("GEMINI_TIMEOUT_S") or 20),
        media_backend=(os.getenv("MEDIA_BACKEND") or "local").lower(),
        media_dir=os.getenv("MEDIA_DIR") or "./media-data",
        media_bucket=os.getenv("MEDIA_BUCKET") or "",
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES") or 10 * 1024 * 1024),
    )
