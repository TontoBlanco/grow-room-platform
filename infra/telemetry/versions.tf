# infra/telemetry/versions.tf  - a SEPARATE, long-lived root. It survives aws-poc teardowns.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }
  backend "s3" {
    bucket       = "grow-room-tfstate-590183769702"
    key          = "aws-poc/telemetry/terraform.tfstate" # under aws-poc/ so the existing plan role can read it
    region       = "us-west-2"
    encrypt      = true
    kms_key_id   = "arn:aws:kms:us-west-2:590183769702:key/213eaa3b-3fa7-4989-a1eb-74765b0db4b9"
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-west-2"
  default_tags {
    tags = {
      Project     = "grow-room"
      Environment = "telemetry"
      ManagedBy   = "terraform"
    }
  }
}