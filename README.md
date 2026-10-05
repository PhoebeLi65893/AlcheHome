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

## Develop without Docker

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
