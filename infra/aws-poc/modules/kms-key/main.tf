# ---------- infra/aws-poc/modules/kms-key/main.tf ----------
variable "alias" { type = string } # without the alias/ prefix
variable "description" { type = string }
variable "extra_policy_documents" {
  description = "JSON policy docs merged into the key policy (service principals)"
  type        = list(string)
  default     = []
}
variable "deletion_window_in_days" {
  type    = number
  default = 7 # the minimum KMS allows
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "this" {
  source_policy_documents = var.extra_policy_documents

  # Lets IAM policies in THIS account grant use of the key. Without it, only
  # principals named in the key policy could ever touch the key.
  statement {
    sid       = "AccountRootEnablesIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "this" {
  description             = var.description
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = var.deletion_window_in_days
  policy                  = data.aws_iam_policy_document.this.json
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.alias}"
  target_key_id = aws_kms_key.this.key_id
}

output "arn" { value = aws_kms_key.this.arn }
output "key_id" { value = aws_kms_key.this.key_id }
output "alias_name" { value = aws_kms_alias.this.name }