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

## T8 demo: ticket creation via function calling

When the assistant knows the problem, urgency and ZIP code, it summarizes and asks whether to create a repair
request. When you agree, Gemini calls the `create_repair_ticket` tool. The API then:

1. validates the arguments (`core-api/app/tickets/schema.py`): category and urgency from fixed lists, a 10-500
   character summary, a 5-digit ZIP. Invalid arguments create nothing; the assistant asks for what is missing.
2. creates the ticket as DRAFT and moves it to OPEN through the state machine (`app/tickets/state.py`), recording
   both steps in `ticket_events`, links it to the conversation and attaches the conversation's photos.
3. writes the confirmation (with the real ticket number) itself, and the chat shows a ticket card.

One ticket per conversation: after it exists the tool is no longer offered. **New request** starts a fresh
conversation. API: `GET /tickets`, `GET /tickets/{id}` (with events and photos), `POST /tickets/{id}/cancel`,
`POST /chat/new`.

**Testing without Gemini** (local only, `APP_ENV=local` and no `GEMINI_API_KEY`): type
`/ticket CATEGORY URGENCY ZIP summary`, e.g. `/ticket plumbing same_day 92101 Kitchen sink dripping under the cabinet`.
It runs the same validation and creation code as the Gemini tool call.

## T9 demo: SMS through Twilio

`POST /webhooks/twilio/sms` receives texts sent to your Twilio number:

1. It checks the `X-Twilio-Signature` header (HMAC of the public URL and parameters with your auth token).
   Requests without a valid signature get 403; without `TWILIO_AUTH_TOKEN` the endpoint is off (503).
2. It records the `MessageSid`, so if Twilio delivers the same message twice it is handled once.
3. It answers Twilio at once and handles the message afterwards with the same code as the web chat
   (`app/conversations.py`): safety rules, Gemini, tickets, MMS photos. The reply goes out through Twilio's REST API.

A new phone number becomes a guest customer. Keywords: STOP (and other opt-out words) stops all messages until
START; HELP is answered by Twilio; NEW starts a new request. Phone numbers are masked in logs.

**Without a Twilio account**: set `TWILIO_AUTH_TOKEN=dev-local-token` in `.env`, `docker compose up -d`, then
`docker compose exec core-api python -m scripts.sim_sms "+16195550199" "my sink is leaking"`. It sends a correctly
signed fake webhook and prints the reply that would be texted back.

**With Twilio**: buy a number (the free trial works), run `ngrok http 8000`, set `PUBLIC_BASE_URL` to the ngrok https
URL and the `TWILIO_*` values in `.env`, `docker compose up -d`, then set the number's "A message comes in" webhook to
`<ngrok url>/webhooks/twilio/sms` (HTTP POST). Test with Twilio's Virtual Phone in the console, or your own verified
phone. Texting real US phones from a 10-digit number needs A2P 10DLC registration.

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

## T10 demo: handyman matching

`core-api/app/matching.py` filters handymen (has the skill, covers the ticket ZIP, available, verified) and ranks them
by `0.4*proximity + 0.3*rating + 0.2*response_rate + 0.1*urgency_fit`. Print the ranking for any ticket:

```bash
docker compose run --rm core-api python -m scripts.seed
docker compose exec core-api python -m scripts.rank_handymen 1024
```

## T11 demo: dispatch by SMS

New tickets stay OPEN until dispatch starts. Start it by hand (or set `DISPATCH_AUTO=true` for automatic dispatch):

```bash
docker compose exec core-api python -m scripts.dispatch_ticket 1024
docker compose exec core-api python -m scripts.sim_sms "+16195550101" "ACCEPT 1024"   # handyman replies
```

One offer is out at a time (expires after 3 min / 15 min / 2 h for emergency / same-day / flexible, or `DISPATCH_TIMEOUT_S`).
Decline or timeout moves to the next-ranked handyman; after 5 offers or no candidates the ticket becomes UNMATCHED.
Handymen reply `ACCEPT 1024` or `DECLINE 1024`; ACCEPT moves the ticket to ASSIGNED. The offer shows the ZIP only.

## T12 demo: ops fallback page

```bash
docker compose exec core-api python -m scripts.make_admin you@example.com   # register that email in the web app first
```

Open `http://localhost:3000/admin.html` and log in. It lists UNMATCHED tickets (or tickets waiting on an offer),
shows every handyman with the right skill (ranked ones first), and assigns one by hand. API: `GET /admin/tickets`,
`GET /admin/tickets/{id}/handymen`, `POST /admin/tickets/{id}/assign`, `POST /admin/tickets/{id}/retry` (ADMIN role only).

## T12-1 demo: Create request button and handyman choice

In the web chat the assistant gives technical suggestions and does not ask for ZIP or urgency. Click **Create request**
when ready: if details are missing the assistant asks for them, then the ticket is created. On the ticket card choose a
handyman (your pick is asked first) or **Find me a handyman** (best ranked first). If the handyman declines or does not
answer, the offers continue down the ranking until someone accepts. API: `POST /chat/request-ticket`,
`GET /tickets/{id}/handymen`, `POST /tickets/{id}/dispatch` with an optional `handyman_id`. SMS chats still ask you to reply OK.
