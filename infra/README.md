# infra (T3): GCP dev environment

Creates: Artifact Registry, Cloud SQL (PostgreSQL 16), Secret Manager (DB password), Cloud Storage (media),
Pub/Sub topics, a runtime service account, the core-api Cloud Run service and a migration Cloud Run job.

Estimated cost is roughly $10-15/month, mostly Cloud SQL, while it exists. Run `terraform destroy` when you are done.

## Steps
1. `gcloud auth login` and `gcloud auth application-default login`, then `gcloud config set project <id>`. Billing must be enabled.
2. `copy terraform.tfvars.example terraform.tfvars` and set `project_id`.
3. `terraform init`, then `terraform apply`. The first apply deploys Google's placeholder image.
4. Build and push the real image:
   `gcloud builds submit ../core-api --tag "$(terraform output -raw artifact_registry_url)/core-api:v1"`
5. Deploy it: `terraform apply -var "core_api_image=<registry-url>/core-api:v1"`
6. Run migrations: `gcloud run jobs execute alche-dev-migrate --region us-west1 --wait`
7. `curl.exe "$(terraform output -raw core_api_url)/health"`
