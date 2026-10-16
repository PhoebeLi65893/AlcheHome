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

variable "web_image" {
  description = "Container image for the web pages. The default is Google's placeholder until the release pipeline pushes the real one."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "min_instances" {
  description = "Instances of core-api that always run (1 keeps the offer-timeout sweeper alive)"
  type        = number
  default     = 1
}

variable "test_mode" {
  description = "Public test deployment: phone verification codes are returned in the response because SMS may not be available. Never enable for production."
  type        = bool
  default     = false
}

variable "dispatch_auto" {
  description = "Offer new tickets to handymen automatically (otherwise tickets wait for the customer's choice or an admin)"
  type        = bool
  default     = false
}

variable "extra_web_origins" {
  description = "More web origins allowed to call the API (for example a custom domain)"
  type        = list(string)
  default     = []
}

variable "github_repo" {
  description = "GitHub repository (owner/name) allowed to deploy through Workload Identity Federation. Empty skips the deploy access."
  type        = string
  default     = ""
}

variable "gemini_model" {
  type    = string
  default = "gemini-3.5-flash"
}

variable "gemini_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "twilio_account_sid" {
  type      = string
  default   = ""
  sensitive = true
}

variable "twilio_auth_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "twilio_from_number" {
  type    = string
  default = ""
}

variable "google_client_id" {
  type    = string
  default = ""
}

variable "google_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "facebook_app_id" {
  type    = string
  default = ""
}

variable "facebook_app_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "web_domain" {
  description = "Your own address for the web pages, for example app.example.com (leave empty to use the run.app address)"
  type        = string
  default     = ""
}
