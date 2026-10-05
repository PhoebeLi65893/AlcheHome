variable "project_id" {
  description = "GCP project ID for the dev environment"
  type        = string
}

variable "region" {
  type    = string
  default = "us-west1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "name_prefix" {
  type    = string
  default = "alche"
}

variable "db_tier" {
  description = "Cloud SQL machine tier (db-f1-micro is the cheapest)"
  type        = string
  default     = "db-f1-micro"
}

variable "core_api_image" {
  description = "Container image for core-api. The default is Google's placeholder so the first apply works before you push your own image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "allow_public_access" {
  description = "Let anyone call the core-api URL (needed for the /health demo)"
  type        = bool
  default     = true
}
