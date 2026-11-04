# Phase 8 backup identity. The telemetry bucket and alias/grow-room/telemetry
# already exist in this root. This role is the only identity the move uses
# for ha-backups/. It is not the shipper role and it cannot read readings/.
#
# Apply this root once before aws-poc.ps1 up -WithHA. A plain aws-poc up does
# not apply this file. The role is free. The telemetry KMS key is the existing
# monthly key, not a new one.

data "aws_iam_policy_document" "ha_backup_trust" {
  statement {
    sid     = "EksPodIdentity"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }

  # The GrowRoom CLI profile is the AdministratorAccess SSO role in this
  # account (see admin_principal_arn on the aws-poc stack). The wildcard
  # avoids copying that role's unique suffix into a second file.
  statement {
    sid     = "HomeOperator"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.me.account_id}:root"]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:PrincipalArn"
      values = [
        "arn:aws:iam::${data.aws_caller_identity.me.account_id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_*",
        "arn:aws:iam::${data.aws_caller_identity.me.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_AdministratorAccess_*",
      ]
    }
  }
}

resource "aws_iam_role" "ha_backup" {
  name                 = "grow-room-ha-backup"
  description          = "Read and write ha-backups/ on the telemetry bucket with the telemetry KMS key."
  assume_role_policy   = data.aws_iam_policy_document.ha_backup_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "ha_backup" {
  statement {
    sid       = "ListHaBackupPrefix"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.telemetry.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["ha-backups/", "ha-backups/*"]
    }
  }

  statement {
    sid = "ReadWriteHaBackups"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.telemetry.arn}/ha-backups/*"]
  }

  statement {
    sid = "UseTelemetryKey"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.telemetry.arn]
  }
}

resource "aws_iam_role_policy" "ha_backup" {
  name   = "ha-backups"
  role   = aws_iam_role.ha_backup.id
  policy = data.aws_iam_policy_document.ha_backup.json
}

output "ha_backup_role_arn" {
  value = aws_iam_role.ha_backup.arn
}
