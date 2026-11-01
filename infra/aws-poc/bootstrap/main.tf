terraform {
  required_version = ">= 1.11.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.71" }
  }
}

provider "aws" {
  region = "us-west-2"
  default_tags {
    tags = { Project = "grow-room", Environment = "poc", ManagedBy = "terraform" }
  }
}

variable "alert_email" { type = string }
variable "github_repo" {
  type    = string
  default = "TontoBlanco/grow-room-platform"
}

locals { account_id = "590183769702" }

# ---------- KMS key for Terraform state (kept between sessions) ----------
data "aws_iam_policy_document" "tfstate_key" {
  statement {
    sid       = "AccountRootEnablesIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "tfstate" {
  description             = "grow-room Terraform state"
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.tfstate_key.json
}

resource "aws_kms_alias" "tfstate" {
  name          = "alias/grow-room/tfstate"
  target_key_id = aws_kms_key.tfstate.key_id
}

# ---------- Route 53 hosted zone (kept between sessions) ----------
variable "domain" {
  description = "Zone name: a domain you registered in Route 53 (e.g. mygrowroom.click) or a subdomain you delegate (e.g. aws.yourdomain.com)"
  type        = string
}

variable "domain_registered_in_route53" {
  description = "true = bought in Route 53, which auto-created the zone. false = Terraform creates a zone you delegate from another DNS provider."
  type        = bool
  default     = true
}

data "aws_route53_zone" "registered" {
  count = var.domain_registered_in_route53 ? 1 : 0
  name  = var.domain
}

resource "aws_route53_zone" "delegated" {
  count   = var.domain_registered_in_route53 ? 0 : 1
  name    = var.domain
  comment = "grow-room PoC - kept across sessions"
  lifecycle { prevent_destroy = true } # new zone = new name servers = re-delegate
}

locals {
  zone_id      = var.domain_registered_in_route53 ? data.aws_route53_zone.registered[0].zone_id : aws_route53_zone.delegated[0].zone_id
  name_servers = var.domain_registered_in_route53 ? data.aws_route53_zone.registered[0].name_servers : aws_route53_zone.delegated[0].name_servers
}

# ---------- Remote state bucket ----------
resource "aws_s3_bucket" "tfstate" {
  bucket = "grow-room-tfstate-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tfstate.arn
    }
    bucket_key_enabled = true # one data key per bucket, far fewer KMS calls
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------- Budgets: email at $10 actual, $25 actual, and forecast > $25 ----------
resource "aws_budgets_budget" "monthly" {
  name         = "grow-room-monthly"
  budget_type  = "COST"
  limit_amount = "25"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 10
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---------- GitHub Actions OIDC (no stored AWS keys in GitHub) ----------
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "plan_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [
        "repo:${var.github_repo}:*",
        "repo:TontoBlanco@173013503/grow-room-platform@1431393221:*",
      ]
    }
  }
}

data "aws_iam_policy_document" "apply_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs that run in the protected "aws-poc" GitHub environment
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [
        "repo:${var.github_repo}:environment:aws-poc",
        "repo:TontoBlanco@173013503/grow-room-platform@1431393221:environment:aws-poc",
      ]
    }
  }
}

resource "aws_iam_role" "gha_plan" {
  name               = "grow-room-gha-plan"
  assume_role_policy = data.aws_iam_policy_document.plan_trust.json
}

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.gha_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# plan must write the .tflock object, so it gets state-bucket write
resource "aws_iam_role_policy" "plan_state" {
  name = "tfstate-rw"
  role = aws_iam_role.gha_plan.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.tfstate.arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.tfstate.arn}/aws-poc/*" },
      # ReadOnlyAccess cannot decrypt; state objects are now KMS-encrypted
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = aws_kms_key.tfstate.arn }
    ]
  })
}

resource "aws_iam_role" "gha_apply" {
  name               = "grow-room-gha-apply"
  assume_role_policy = data.aws_iam_policy_document.apply_trust.json
}

# Demo shortcut: admin for apply/destroy. Production would scope this down.
resource "aws_iam_role_policy_attachment" "apply_admin" {
  role       = aws_iam_role.gha_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "state_bucket" { value = aws_s3_bucket.tfstate.bucket }
output "plan_role_arn" { value = aws_iam_role.gha_plan.arn }
output "apply_role_arn" { value = aws_iam_role.gha_apply.arn }
output "tfstate_kms_key_arn" { value = aws_kms_key.tfstate.arn }
output "zone_id" { value = local.zone_id }
output "name_servers" { value = local.name_servers }