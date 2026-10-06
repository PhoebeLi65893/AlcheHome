# Alche Home

AI-powered home repair dispatch platform. See `docs/` for the PRD, System Architecture Document and task list.

## Layout

| Folder | Purpose | Task |
|---|---|---|
| `core-api/` | FastAPI core API (auth, tickets, webhooks) | T1, T4+ |
| `ai-agent/` | Gemini agent service | T6+ |
| `dispatcher/` | Matching and dispatch worker | T10+ |
| `pipeline/` | PII redaction and fine-tuning ETL | T19+ |
| `web/` | Web app (static login page for now, served by nginx) | T4+ |
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

## T4 demo: authentication

1. Copy `.env.example` to `.env` and set `JWT_SECRET` (any long random string).
2. Optional social login. Create OAuth credentials and put them in `.env`:
   - Google: Cloud Console > APIs & Services > Credentials > OAuth client ID (Web). Authorized redirect URI: `http://localhost:8000/auth/google/callback`.
   - Facebook: developers.facebook.com > create app > Facebook Login. Valid redirect URI: `http://localhost:8000/auth/facebook/callback`.
3. `docker compose up -d --build`, then open `http://localhost:3000`.

API: `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`; `GET /auth/{google|facebook}/login`; `GET /me`.
Access tokens last 15 minutes. Refresh tokens last 30 days, rotate on every use, and reuse of an old one ends all of that user's sessions.

## T5 demo: chat shell with echo bot

After signing in at `http://localhost:3000` the chat panel appears. Every message you send is stored in the
`messages` table and answered by an echo bot (`core-api/app/bot.py`, replaced by Gemini in T6).

API: `GET /chat/messages` (history, creates your single ACTIVE web conversation if needed) and
`POST /chat/messages` with `{"body": "..."}`. Both need an `Authorization: Bearer <access token>` header.

```bash
docker compose exec db psql -U alche alche -c "SELECT sender, body, created_at FROM messages ORDER BY created_at DESC LIMIT 10"
```

## T6 demo: Gemini intake and emergency safety rules

Get an API key at https://aistudio.google.com and put `GEMINI_API_KEY=...` in `.env`, then `docker compose up -d --build`.
Without a key the chat falls back to the T5 echo bot. Model names change over time: if the API reports the model is
not found, set `GEMINI_MODEL` to a current one (see https://ai.google.dev/gemini-api/docs/models).

- The safety layer (`app/agent/safety.py`) checks every message first with fixed rules (gas, carbon monoxide, fire,
  sparking wiring, water near electricity, structural collapse). A match returns fixed 911 guidance instantly,
  never calls Gemini, and is stored with `messages.flag = 'EMERGENCY'` (shown in red).
- Otherwise the last 20 messages go to Gemini Flash with the intake instructions in `app/agent/prompt.py`.
- If Gemini fails, the user gets a short apology that repeats the 911 reminder, and the chat keeps working.
- Do not use real personal data while testing: messages are sent to Google's API.

## T7 demo: photo upload and image analysis

In the chat, click **Photo**, pick up to 3 JPEG/PNG/WebP photos (10 MB each), add a note if you like, and send.

- `POST /media` (multipart field `file`) checks the file really is an image, re-encodes it as JPEG,
  removes EXIF metadata (including the GPS location phones add), fixes rotation and shrinks it to at most
  1600 px. `GET /media/{id}` returns it, only to its owner.
- `POST /chat/messages` accepts `{"body": "...", "media_ids": ["..."]}`. The photos of the newest message are
  sent to Gemini, which describes what it sees, names the likely issue and gives `Severity: Low/Medium/High/Emergency`.
  Earlier photos are only mentioned as `[photo attached]` to keep requests small.
- Storage: a Docker volume (`media`) locally; the Cloud Storage bucket from T3 in the cloud (`MEDIA_BACKEND=gcs`).
- Without a Gemini key the echo bot answers "(received 1 photo)".

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
