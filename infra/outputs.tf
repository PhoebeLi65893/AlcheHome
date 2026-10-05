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
