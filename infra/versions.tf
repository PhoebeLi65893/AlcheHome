terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Dev uses local state. To share state later, add a GCS backend here.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
