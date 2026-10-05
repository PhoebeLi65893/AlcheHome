locals {
  name = "${var.name_prefix}-${var.environment}"

  apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "pubsub.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
  ]

  topics = ["message-received", "ticket-created", "offer-expired", "dead-letter"]

  db_env = {
    APP_ENV                  = var.environment
    DB_USER                  = google_sql_user.app.name
    DB_NAME                  = google_sql_database.app.name
    INSTANCE_CONNECTION_NAME = google_sql_database_instance.pg.connection_name
  }
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

# ---------- Container registry ----------
resource "google_artifact_registry_repository" "images" {
  repository_id = local.name
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ---------- Database (PostgreSQL 16; pgvector is enabled by the T2 migration) ----------
resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "${local.name}-db-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "google_secret_manager_secret" "jwt" {
  secret_id = "${local.name}-jwt-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "jwt" {
  secret      = google_secret_manager_secret.jwt.id
  secret_data = random_password.jwt.result
}

resource "google_sql_database_instance" "pg" {
  name                = "${local.name}-pg"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false # dev only

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    backup_configuration {
      enabled = true
    }
    ip_configuration {
      ipv4_enabled = true # no authorized networks: only reachable through the Cloud SQL connector
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  name     = "alche"
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "app" {
  name     = "alche"
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

# ---------- Media storage ----------
resource "google_storage_bucket" "media" {
  name                        = "${var.project_id}-${local.name}-media"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true # dev only
  public_access_prevention    = "enforced"
  depends_on                  = [google_project_service.apis]
}

# ---------- Messaging ----------
resource "google_pubsub_topic" "topics" {
  for_each   = toset(local.topics)
  name       = "${local.name}-${each.value}"
  depends_on = [google_project_service.apis]
}

# ---------- Identity ----------
resource "google_service_account" "run" {
  account_id   = "${local.name}-run"
  display_name = "Alche Home Cloud Run runtime"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "run_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.run.email}"
}

resource "google_project_iam_member" "run_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_db_password" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_jwt" {
  secret_id = google_secret_manager_secret.jwt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_storage_bucket_iam_member" "run_media" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.run.email}"
}

# ---------- core-api (Cloud Run service) ----------
resource "google_cloud_run_v2_service" "core_api" {
  name                = "${local.name}-core-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # dev only

  template {
    service_account = google_service_account.run.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.pg.connection_name]
      }
    }

    containers {
      image = var.core_api_image

      dynamic "env" {
        for_each = local.db_env
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
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt.secret_id
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

  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.run_db_password,
    google_secret_manager_secret_version.jwt,
    google_secret_manager_secret_iam_member.run_jwt,
    google_project_iam_member.run_sql,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_public_access ? 1 : 0
  name     = google_cloud_run_v2_service.core_api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------- Migration job (runs alembic against Cloud SQL) ----------
resource "google_cloud_run_v2_job" "migrate" {
  name                = "${local.name}-migrate"
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
        command = ["alembic"]
        args    = ["upgrade", "head"]

        dynamic "env" {
          for_each = local.db_env
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

  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.run_db_password,
    google_project_iam_member.run_sql,
  ]
}
