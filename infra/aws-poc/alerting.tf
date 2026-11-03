# infra/aws-poc/alerting.tf
resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts" # grow-room-poc-alerts
  kms_master_key_id = "alias/aws/sns"        # AWS-managed key: free, same-account publishers allowed
}

# Created only when alert_email is set. scripts/aws-poc.ps1 up passes
# -var alert_email from ALERT_EMAIL (env, terraform.tfvars, or the GitHub
# variable) and, after apply, checks for PendingConfirmation. CI apply sets
# TF_VAR_alert_email from the same GitHub variable. The inbox link still has
# to be clicked; Terraform does not wait for that.
resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

data "aws_iam_policy_document" "alertmanager_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "alertmanager" {
  name               = "${local.name}-alertmanager"
  assume_role_policy = data.aws_iam_policy_document.alertmanager_trust.json
}

resource "aws_iam_role_policy" "alertmanager" {
  name = "sns-publish"
  role = aws_iam_role.alertmanager.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = aws_sns_topic.alerts.arn
    }]
  })
}

resource "aws_eks_pod_identity_association" "alertmanager" {
  cluster_name    = module.eks.cluster_name
  namespace       = "monitoring"
  service_account = "alertmanager"
  role_arn        = aws_iam_role.alertmanager.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}