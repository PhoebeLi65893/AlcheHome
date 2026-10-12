output "core_api_url" {
  value = google_cloud_run_v2_service.core_api.uri
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "migrate_job_name" {
  value = google_cloud_run_v2_job.migrate.name
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.pg.connection_name
}

output "media_bucket" {
  value = google_storage_bucket.media.name
}

output "pubsub_topics" {
  value = [for t in google_pubsub_topic.topics : t.name]
}

output "web_url" {
  description = "Open this to use the app (customer page; /handyman.html and /admin.html on the same address)"
  value       = google_cloud_run_v2_service.web.uri
}

output "api_url" {
  value = google_cloud_run_v2_service.core_api.uri
}

output "tools_job_name" {
  value = google_cloud_run_v2_job.tools.name
}

output "deployer_service_account" {
  description = "Set as the GCP_DEPLOYER_SA variable of the GitHub environment"
  value       = var.github_repo != "" ? google_service_account.deployer[0].email : null
}

output "workload_identity_provider" {
  description = "Set as the GCP_WORKLOAD_IDENTITY_PROVIDER variable of the GitHub environment"
  value       = var.github_repo != "" ? google_iam_workload_identity_pool_provider.github[0].name : null
}

output "name" {
  description = "Prefix of the Cloud Run services and jobs (NAME_PREFIX-ENV)"
  value       = local.name
}
