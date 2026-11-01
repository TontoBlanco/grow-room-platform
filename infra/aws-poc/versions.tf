terraform {
  required_version = ">= 1.11.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.71" }
  }

  backend "s3" {
    bucket       = "grow-room-tfstate-590183769702"
    key          = "aws-poc/terraform.tfstate"
    region       = "us-west-2"
    encrypt      = true
    kms_key_id   = "arn:aws:kms:us-west-2:590183769702:key/213eaa3b-3fa7-4989-a1eb-74765b0db4b9" # tfstate_kms_key_arn; without this, encrypt=true forces SSE-S3
    use_lockfile = true                                                                          # S3-native locking; no DynamoDB table needed
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "grow-room"
      Environment = "poc"
      ManagedBy   = "terraform"
      Owner       = "cole"
    }
  }
}