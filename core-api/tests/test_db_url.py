from app.db import database_url


def test_database_url_prefers_explicit_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    assert database_url() == "postgresql+psycopg://u:p@h:5432/d"


def test_database_url_builds_cloud_sql_socket_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "s3cret/x")
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:us-west1:inst")
    url = database_url()
    assert url.startswith("postgresql+psycopg://alche:")
    assert "host=%2Fcloudsql%2Fproj%3Aus-west1%3Ainst" in url
