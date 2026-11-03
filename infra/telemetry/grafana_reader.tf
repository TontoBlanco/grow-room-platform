# Read-only Roles Anywhere identity for the local Grafana Athena plugin.
# Separate profile and certificate CN from grow-room-home-shipper. The shipper
# trust policy requires CN grow-room-home-shipper, so this cert cannot assume
# that role, and the shipper cert cannot assume this one.

locals {
  glue_catalog_arn  = "arn:aws:glue:us-west-2:${data.aws_caller_identity.me.account_id}:catalog"
  glue_database_arn = "arn:aws:glue:us-west-2:${data.aws_caller_identity.me.account_id}:database/${aws_glue_catalog_database.telemetry.name}"
  glue_tables_arn   = "arn:aws:glue:us-west-2:${data.aws_caller_identity.me.account_id}:table/${aws_glue_catalog_database.telemetry.name}/*"
}

data "aws_iam_policy_document" "grafana_reader_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"]
    principals {
      type        = "Service"
      identifiers = ["rolesanywhere.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_rolesanywhere_trust_anchor.home.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalTag/x509Subject/CN"
      values   = ["grow-room-grafana-reader"]
    }
  }
}

resource "aws_iam_role" "grafana_reader" {
  name                 = "grow-room-grafana-reader"
  description          = "Read grow-room telemetry through Athena. No write to readings/."
  assume_role_policy   = data.aws_iam_policy_document.grafana_reader_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "grafana_reader" {
  statement {
    sid = "QueryWorkgroup"
    actions = [
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetQueryResultsStream",
      "athena:BatchGetQueryExecution",
      "athena:ListQueryExecutions",
      "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.telemetry.arn]
  }

  # These list/describe calls do not support a workgroup resource ARN.
  statement {
    sid = "AthenaListUnscoped"
    actions = [
      "athena:ListWorkGroups",
      "athena:ListEngineVersions",
      "athena:ListDataCatalogs",
      "athena:GetDataCatalog",
      "athena:ListDatabases",
      "athena:ListTableMetadata",
      "athena:GetTableMetadata",
    ]
    resources = ["*"]
  }

  statement {
    sid = "GlueReadTelemetry"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
    ]
    resources = [
      local.glue_catalog_arn,
      local.glue_database_arn,
      local.glue_tables_arn,
    ]
  }

  statement {
    sid       = "LocateBucket"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.telemetry.arn]
  }

  statement {
    sid = "ListTelemetryPrefixes"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [aws_s3_bucket.telemetry.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "readings",
        "readings/*",
        "athena-results",
        "athena-results/*",
      ]
    }
  }

  statement {
    sid = "ReadDataAndResults"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "${aws_s3_bucket.telemetry.arn}/readings/*",
      "${aws_s3_bucket.telemetry.arn}/athena-results/*",
    ]
  }

  # Athena writes the result CSV under the workgroup output location only.
  statement {
    sid = "WriteQueryResults"
    actions = [
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.telemetry.arn}/athena-results/*"]
  }

  statement {
    sid    = "DenyWriteReadings"
    effect = "Deny"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.telemetry.arn}/readings/*"]
  }

  # Decrypt reads SSE-KMS objects (bucket key). GenerateDataKey writes the
  # workgroup's SSE-KMS result objects. DescribeKey is the call S3 makes first.
  # This is not permission to write readings; DenyWriteReadings blocks that.
  statement {
    sid = "UseTelemetryKey"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.telemetry.arn]
  }
}

resource "aws_iam_role_policy" "grafana_reader" {
  name   = "query-telemetry"
  role   = aws_iam_role.grafana_reader.id
  policy = data.aws_iam_policy_document.grafana_reader.json
}

resource "aws_rolesanywhere_profile" "grafana" {
  name             = "grow-room-grafana"
  enabled          = true
  role_arns        = [aws_iam_role.grafana_reader.arn]
  duration_seconds = 3600
}

output "grafana_role_arn" {
  value = aws_iam_role.grafana_reader.arn
}

output "grafana_profile_arn" {
  value = aws_rolesanywhere_profile.grafana.arn
}
