# Alche Home

AI-powered home repair dispatch platform. See `docs/` for the PRD, System Architecture Document and task list.

## Layout

| Folder | Purpose | Task |
|---|---|---|
| `core-api/` | FastAPI core API (auth, tickets, webhooks) | T1, T4+ |
| `ai-agent/` | Gemini agent service | T6+ |
| `dispatcher/` | Matching and dispatch worker | T10+ |
| `pipeline/` | PII redaction and fine-tuning ETL | T19+ |
| `web/` | Web app | T4+ |
| `infra/` | Terraform | T3 |
| `docs/` | PRD, SAD, task list | |

## Run locally (T1 demo)

```bash
docker compose up --build
curl http://localhost:8000/health
```

Expected: `{"status":"ok","service":"core-api",...}`

## T2 demo: database, migrations, seed data

```bash
docker compose up -d --build          # starts Postgres+pgvector, runs migrations, starts the API
docker compose run --rm core-api python -m scripts.seed
docker compose exec db psql -U alche alche -c "SELECT display_name, rating_avg, service_zips FROM handymen ORDER BY rating_avg DESC"
```

Connect a SQL client (DBeaver, pgAdmin, VS Code) to `localhost:5432`, user/password/database `alche`.
Reset everything: `docker compose down -v`. Roll back one migration: `docker compose run --rm core-api alembic downgrade -1`.

## Develop without Docker (needs a local Postgres with pgvector; set DATABASE_URL)

```bash
cd core-api
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest
uvicorn app.main:app --reload
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs lint, format check, tests and a Docker build with a `/health` smoke test on every push to `main` and every pull request.
