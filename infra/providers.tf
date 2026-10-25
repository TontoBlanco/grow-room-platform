# Default provider for the account/region you plan against.
# CI runs `terraform validate` with -backend=false and no credentials;
# AWS API calls only happen on plan/apply.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
