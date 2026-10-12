#!/usr/bin/env bash
# Release the current commit to Google Cloud (used by .github/workflows/deploy.yml).
#
# Order matters and each step stops the release if it fails:
#   1. build and push the core-api and web images
#   2. run the database migrations (a broken migration deploys nothing)
#   3. deploy the new core-api revision with no traffic, smoke-test it on its own URL
#   4. move traffic to it, smoke-test again, and roll back to the previous revision on failure
#   5. deploy the web pages the same way, pointed at the API
#
# Required environment: PROJECT_ID REGION ENVIRONMENT (dev|prod) SHORT_SHA
# Optional: NAME_PREFIX (default alche)
# Needs: gcloud (authenticated), docker, curl, python3
set -euo pipefail

: "${PROJECT_ID:?}" "${REGION:?}" "${ENVIRONMENT:?}" "${SHORT_SHA:?}"
NAME="${NAME_PREFIX:-alche}-${ENVIRONMENT}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${NAME}"
API_SERVICE="${NAME}-core-api"
WEB_SERVICE="${NAME}-web"
REV="r${SHORT_SHA}"
API_IMAGE="${REGISTRY}/core-api:${SHORT_SHA}"
WEB_IMAGE="${REGISTRY}/web:${SHORT_SHA}"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

service_url() {
  gcloud run services describe "$1" --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.url)'
}

# https://svc-123.region.run.app  ->  https://candidate---svc-123.region.run.app
tag_url() {
  python3 - "$1" "$2" <<'PY'
import sys
url, tag = sys.argv[1], sys.argv[2]
scheme, rest = url.split("://", 1)
print(f"{scheme}://{tag}---{rest}")
PY
}

wait_for() { # url, grep pattern, what
  local url="$1" pattern="$2" what="$3" body=""
  for _ in $(seq 1 30); do
    body="$(curl -fsS --max-time 10 "$url" 2>/dev/null || true)"
    if printf '%s' "$body" | grep -q "$pattern"; then
      echo "ok: $what"
      return 0
    fi
    sleep 4
  done
  echo "last response from $url: ${body:0:300}" >&2
  return 1
}

smoke_api() { # base url
  local base="$1"
  wait_for "$base/health" '"status":"ok"' "API /health" || return 1
  # The API must be talking to its database: a wrong login is answered 401, not 5xx.
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST "$base/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"email":"smoke-test@example.invalid","password":"not-a-real-password"}')"
  [ "$code" = "401" ] || { echo "login check returned HTTP $code (expected 401)" >&2; return 1; }
  echo "ok: API reaches its database"
}

smoke_web() { # base url, expected api url
  local base="$1" api="$2"
  wait_for "$base/" 'Alche Home' "web page" || return 1
  wait_for "$base/config.js" "$api" "web config points at the API" || return 1
  wait_for "$base/handyman.html" 'Alche Home Pro' "handyman page" || return 1
}

previous_revision() {
  gcloud run services describe "$1" --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.traffic[0].revisionName)' 2>/dev/null || true
}

log "Checking that the environment exists"
gcloud run services describe "$API_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --format='value(name)' >/dev/null ||
  fail "$API_SERVICE not found. Create the environment first (terraform apply in infra/)."

log "Building and pushing images"
docker build -t "$API_IMAGE" ./core-api
docker build -t "$WEB_IMAGE" ./web
docker push "$API_IMAGE"
docker push "$WEB_IMAGE"

log "Updating the migration and tools jobs"
gcloud run jobs update "${NAME}-migrate" --project "$PROJECT_ID" --region "$REGION" --image "$API_IMAGE"
gcloud run jobs update "${NAME}-tools" --project "$PROJECT_ID" --region "$REGION" --image "$API_IMAGE"

log "Running database migrations"
gcloud run jobs execute "${NAME}-migrate" --project "$PROJECT_ID" --region "$REGION" --wait ||
  fail "Migrations failed. Nothing was deployed; the running revision is untouched."

log "Deploying the API revision ${API_SERVICE}-${REV} with no traffic"
gcloud run deploy "$API_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --image "$API_IMAGE" --revision-suffix "$REV" --no-traffic --tag candidate --quiet

API_URL="$(service_url "$API_SERVICE")"
CANDIDATE_URL="$(tag_url "$API_URL" candidate)"
log "Smoke-testing the candidate at $CANDIDATE_URL"
smoke_api "$CANDIDATE_URL" || fail "The new API revision failed its checks and received no traffic."

log "Moving traffic to ${API_SERVICE}-${REV}"
PREVIOUS="$(previous_revision "$API_SERVICE")"
gcloud run services update-traffic "$API_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --to-latest --quiet
if ! smoke_api "$API_URL"; then
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "${API_SERVICE}-${REV}" ]; then
    echo "Rolling back to $PREVIOUS" >&2
    gcloud run services update-traffic "$API_SERVICE" --project "$PROJECT_ID" \
      --region "$REGION" --to-revisions "${PREVIOUS}=100" --quiet
  fi
  fail "The API failed its checks after the switch and was rolled back."
fi

log "Deploying the web pages ${WEB_SERVICE}-${REV} with no traffic"
gcloud run deploy "$WEB_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --image "$WEB_IMAGE" --revision-suffix "$REV" --no-traffic --tag candidate \
  --set-env-vars "API_BASE=${API_URL}" --quiet
WEB_URL="$(service_url "$WEB_SERVICE")"
smoke_web "$(tag_url "$WEB_URL" candidate)" "$API_URL" ||
  fail "The new web revision failed its checks and received no traffic."

WEB_PREVIOUS="$(previous_revision "$WEB_SERVICE")"
gcloud run services update-traffic "$WEB_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --to-latest --quiet
if ! smoke_web "$WEB_URL" "$API_URL"; then
  if [ -n "$WEB_PREVIOUS" ] && [ "$WEB_PREVIOUS" != "${WEB_SERVICE}-${REV}" ]; then
    gcloud run services update-traffic "$WEB_SERVICE" --project "$PROJECT_ID" \
      --region "$REGION" --to-revisions "${WEB_PREVIOUS}=100" --quiet
  fi
  fail "The web pages failed their checks after the switch and were rolled back."
fi

log "Released ${SHORT_SHA}"
echo "Customer app : ${WEB_URL}/"
echo "Handyman app : ${WEB_URL}/handyman.html"
echo "Ops page     : ${WEB_URL}/admin.html"
echo "API          : ${API_URL}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Released \`${SHORT_SHA}\` to ${ENVIRONMENT}"
    echo "- Customer app: ${WEB_URL}/"
    echo "- Handyman app: ${WEB_URL}/handyman.html"
    echo "- Ops page: ${WEB_URL}/admin.html"
    echo "- API: ${API_URL}"
  } >>"$GITHUB_STEP_SUMMARY"
fi
