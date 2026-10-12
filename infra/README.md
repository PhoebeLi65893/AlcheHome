# infra: Google Cloud environment and release pipeline (T3, T13-3)

Terraform creates one environment (`alche-<environment>`, default `dev`):

| Piece | What |
|---|---|
| Artifact Registry | the container images |
| Cloud SQL | PostgreSQL 16 (pgvector is enabled by the first migration) |
| Cloud Storage | uploaded photos |
| Secret Manager | database password, JWT secret and, if you provide them, Gemini / Twilio / sign-in secrets |
| Cloud Run `...-core-api` | the API, **one instance always running** (it also runs the job-offer timeout sweeper) |
| Cloud Run `...-web` | the customer, handyman and ops pages (`/`, `/handyman.html`, `/admin.html`) |
| Cloud Run jobs | `...-migrate` (database migrations) and `...-tools` (seed data, make an admin, invite a handyman) |
| Workload Identity Federation | lets this GitHub repository deploy without any stored keys |

Estimated cost is roughly $15-25 per month while it exists (Cloud SQL and the always-on API instance are most of
it). Run `terraform destroy` when you are done.

## 1. Create the environment (once)

1. `gcloud auth login` and `gcloud auth application-default login`, then `gcloud config set project <id>`.
   Billing must be enabled.
2. `copy terraform.tfvars.example terraform.tfvars` and set at least `project_id` and `github_repo` (`owner/name`).
   For a public test deployment keep `allow_public_access = true`, `test_mode = true` and `dispatch_auto = true`.
   Put any keys you have (Gemini, Twilio, Google/Facebook sign-in) in the same file; leave the others out and that
   feature simply stays off. **Do not commit `terraform.tfvars`** (it is in `.gitignore`).
3. `terraform init`, then `terraform apply`. The first apply starts Google's placeholder image.
4. Note the outputs: `terraform output web_url`, `deployer_service_account`, `workload_identity_provider`.

## 2. Connect GitHub (once)

In the repository, **Settings > Environments**, create `dev` (and later `prod`) and add these **variables**:

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | your project id |
| `GCP_REGION` | `us-west1` (or your region) |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `terraform output -raw workload_identity_provider` |
| `GCP_DEPLOYER_SA` | `terraform output -raw deployer_service_account` |
| `NAME_PREFIX` | optional, default `alche` |

For `prod`, add **Required reviewers** so every production release needs an approval.

## 3. Release

* Every push to `main` that passes CI is released to **dev** automatically (`.github/workflows/deploy.yml`).
* To release to prod, or to redeploy an older commit: **Actions > Deploy > Run workflow**.

The pipeline (`deploy/release.sh`) builds the images, runs the database migrations (a failing migration stops
everything and the running version keeps serving), deploys the new API revision with no traffic, smoke-tests it on
its own URL, moves traffic, tests again and rolls back by itself if that fails, then does the same for the web pages.
The run summary lists the public addresses.

To go back to an earlier version by hand:
`gcloud run services update-traffic alche-dev-core-api --region us-west1 --to-revisions <revision>=100`

## 4. Put test data in and make an admin

```bash
# sample handymen (idempotent)
gcloud run jobs execute alche-dev-tools --region us-west1 --wait --args="-m,scripts.seed"
# after registering your account in the web app:
gcloud run jobs execute alche-dev-tools --region us-west1 --wait --args="-m,scripts.make_admin,you@example.com"
# a login link for a seeded handyman:
gcloud run jobs execute alche-dev-tools --region us-west1 --wait --args="-m,scripts.invite_handyman,mike@example.com"
```

The invite link is printed in the job's logs. The ops page (`/admin.html`) can also create handyman accounts.

## Public testing: what to know

* **Open sign-up.** Anyone with the address can register. Sign-up, login, chat and phone-code calls are rate limited
  per client address (see `app/ratelimit.py`); real edge protection is T22.
* **`test_mode`** returns phone verification codes in the response because SMS may not be available. It is meant for
  a public *test* deployment and must be off for production.
* **SMS.** Real text messages need your Twilio account out of review and, for US numbers, A2P registration. Until
  then the in-app flows (offers in the handyman app, messages, profile) work without SMS.
* **Sign in with Google / Facebook.** Add `<api_url>/auth/google/callback` and `<api_url>/auth/facebook/callback` to
  the redirect addresses of those apps, or use email sign-in.
* **Twilio webhook.** Set the number's incoming-message URL to `<api_url>/webhooks/twilio/sms`.
