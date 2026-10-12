# T13-3: everything a public test deployment and the GitHub release pipeline need.
#  - the web pages as their own Cloud Run service
#  - optional secrets (Gemini, Twilio, Google/Facebook sign-in) wired into core-api
#  - a "tools" job to seed handymen, create an admin or invite a handyman
#  - GitHub Actions deploy access through Workload Identity Federation (no stored keys)

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  # Cloud Run's stable URL shape, so each service can know the other's address up front.
  api_url = "https://${local.name}-core-api-${data.google_project.this.number}.${var.region}.run.app"
  web_url = "https://${local.name}-web-${data.google_project.this.number}.${var.region}.run.app"

  # Plain (non-secret) settings for core-api. Empty values are not set at all.
  plain_env = {
    for k, v in {
      API_BASE_URL       = local.api_url
      PUBLIC_BASE_URL    = local.api_url # the URL Twilio calls; used to check its signature
      WEB_BASE_URL       = local.web_url
      CORS_ORIGINS       = join(",", var.extra_web_origins)
      TEST_MODE          = var.test_mode ? "true" : "false"
      DISPATCH_AUTO      = var.dispatch_auto ? "true" : "false"
      GEMINI_MODEL       = var.gemini_model
      TWILIO_FROM_NUMBER = var.twilio_from_number
      GOOGLE_CLIENT_ID   = var.google_client_id
      FACEBOOK_APP_ID    = var.facebook_app_id
    } : k => v if v != ""
  }

  # Secret settings: a secret is only created and wired when you give it a value.
  secret_values = {
    GEMINI_API_KEY       = var.gemini_api_key
    TWILIO_ACCOUNT_SID   = var.twilio_account_sid
    TWILIO_AUTH_TOKEN    = var.twilio_auth_token
    GOOGLE_CLIENT_SECRET = var.google_client_secret
    FACEBOOK_APP_SECRET  = var.facebook_app_secret
  }
  secret_names = nonsensitive([for k, v in local.secret_values : k if v != ""])
}

# ---------- optional secrets ----------
resource "google_secret_manager_secret" "optional" {
  for_each  = toset(local.secret_names)
  secret_id = "${local.name}-${lower(replace(each.value, "_", "-"))}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "optional" {
  for_each    = toset(local.secret_names)
  secret      = google_secret_manager_secret.optional[each.value].id
  secret_data = local.secret_values[each.value]
}

resource "google_secret_manager_secret_iam_member" "run_optional" {
  for_each  = toset(local.secret_names)
  secret_id = google_secret_manager_secret.optional[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

# ---------- web pages (customer, handyman and ops) ----------
resource "google_cloud_run_v2_service" "web" {
  name                = "${local.name}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # dev only

  template {
    service_account = google_service_account.run.email
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    containers {
      image = var.web_image
      ports {
        container_port = 8080
      }
      env {
        name  = "API_BASE"
        value = local.api_url
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image, # the release pipeline deploys new images
      template[0].revision,
      client,
      client_version,
    ]
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  count    = var.allow_public_access ? 1 : 0
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------- tools job: seed data, make an admin, invite a handyman ----------
# gcloud run jobs execute NAME --region R --wait --args="-m,scripts.seed"
resource "google_cloud_run_v2_job" "tools" {
  name                = "${local.name}-tools"
  location            = var.region
  deletion_protection = false # dev only

  template {
    template {
      service_account = google_service_account.run.email
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.pg.connection_name]
        }
      }

      containers {
        image   = var.core_api_image
        command = ["python"]
        args    = ["-m", "scripts.seed"]

        dynamic "env" {
          for_each = merge(local.db_env, { WEB_BASE_URL = local.web_url })
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "DB_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.db_password.secret_id
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.run_db_password,
    google_project_iam_member.run_sql,
  ]
}

# ---------- GitHub Actions deploy access (Workload Identity Federation) ----------
resource "google_service_account" "deployer" {
  count        = var.github_repo != "" ? 1 : 0
  account_id   = "${local.name}-deployer"
  display_name = "Alche Home GitHub Actions deployer"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "deployer" {
  for_each = var.github_repo != "" ? toset([
    "roles/run.admin",
    "roles/artifactregistry.writer",
  ]) : toset([])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

# The deployer may start Cloud Run revisions that run as the runtime account.
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer[0].email}"
}

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repo != "" ? 1 : 0
  workload_identity_pool_id = "${local.name}-github"
  display_name              = "GitHub Actions (${local.name})"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repo != "" ? 1 : 0
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only this repository may use the pool.
  attribute_condition = "assertion.repository == \"${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonates_deployer" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}
