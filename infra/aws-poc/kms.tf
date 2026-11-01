# ---------- infra/aws-poc/kms.tf : one key per purpose ----------
module "kms_eks" {
  source      = "./modules/kms-key"
  alias       = "grow-room-poc/eks-secrets"
  description = "EKS envelope encryption of Kubernetes Secrets"
}

module "kms_rds" {
  source      = "./modules/kms-key"
  alias       = "grow-room-poc/rds"
  description = "RDS audit DB storage, snapshots, backups"
}

module "kms_s3" {
  source      = "./modules/kms-key"
  alias       = "grow-room-poc/s3-sensor"
  description = "Sensor bucket + Athena results"
}

module "kms_secrets" {
  source      = "./modules/kms-key"
  alias       = "grow-room-poc/secrets-manager"
  description = "Secrets Manager: RDS master password"
}

# CloudWatch Logs encrypts with the key itself, so the service needs key-policy access,
# limited to log groups in this account and region.
data "aws_iam_policy_document" "logs_key" {
  statement {
    sid       = "CloudWatchLogsUseKey"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.region}:${local.account_id}:log-group:*"]
    }
  }
}

module "kms_logs" {
  source                 = "./modules/kms-key"
  alias                  = "grow-room-poc/logs"
  description            = "CloudWatch Logs: VPC flow logs + EKS control-plane logs"
  extra_policy_documents = [data.aws_iam_policy_document.logs_key.json]
}

# EBS: whoever LAUNCHES the instance needs the key. The managed node group launches
# through the Auto Scaling service-linked role (its policy can't be edited, so the
# key policy must name it); Karpenter launches with its controller role.
locals {
  ebs_key_users = [
    "arn:aws:iam::${local.account_id}:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling",
    module.karpenter.iam_role_arn,
  ]
}

data "aws_iam_policy_document" "ebs_key" {
  statement {
    sid       = "NodeLaunchersUseKey"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = local.ebs_key_users
    }
  }
  statement {
    sid       = "NodeLaunchersCreateGrantsForEc2"
    actions   = ["kms:CreateGrant"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = local.ebs_key_users
    }
    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }
}

module "kms_ebs" {
  source                 = "./modules/kms-key"
  alias                  = "grow-room-poc/ebs"
  description            = "EBS root volumes for EKS nodes"
  extra_policy_documents = [data.aws_iam_policy_document.ebs_key.json]
}