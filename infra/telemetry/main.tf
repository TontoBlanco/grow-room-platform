# infra/telemetry/main.tf
variable "ca_cert_file" {
  description = "Path to your home CA certificate (PEM). Public part only - never the .key"
  type        = string
  default     = "C:/src/grow-room-pki/ca.pem"
}

data "aws_caller_identity" "me" {}

locals {
  bucket = "grow-room-telemetry-${data.aws_caller_identity.me.account_id}"
}

# ---------- encryption ($1/month) ----------
resource "aws_kms_key" "telemetry" {
  description             = "grow-room telemetry bucket + Athena results"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "telemetry" {
  name          = "alias/grow-room/telemetry"
  target_key_id = aws_kms_key.telemetry.key_id
}

# ---------- the data lake bucket ----------
resource "aws_s3_bucket" "telemetry" {
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "telemetry" {
  bucket                  = aws_s3_bucket.telemetry.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "telemetry" {
  bucket = aws_s3_bucket.telemetry.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "telemetry" {
  bucket = aws_s3_bucket.telemetry.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.telemetry.arn
    }
    bucket_key_enabled = true   # one KMS call per bucket-key period, not per object = cheaper
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "telemetry" {
  bucket = aws_s3_bucket.telemetry.id
  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter {
      prefix = "athena-results/"
    }
    expiration {
      days = 7
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.telemetry.arn, "${aws_s3_bucket.telemetry.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "telemetry" {
  bucket = aws_s3_bucket.telemetry.id
  policy = data.aws_iam_policy_document.tls_only.json
}

# ---------- catalog + query ----------
resource "aws_glue_catalog_database" "telemetry" {
  name = "grow_room_telemetry"
}

resource "aws_glue_catalog_table" "readings" {
  name          = "readings"
  database_name = aws_glue_catalog_database.telemetry.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"                  = "json"
    "projection.enabled"              = "true"
    "projection.dt.type"              = "date"
    "projection.dt.format"            = "yyyy-MM-dd"
    "projection.dt.range"             = "2026-11-01,NOW"
    "projection.dt.interval"          = "1"
    "projection.dt.interval.unit"     = "DAYS"
    "storage.location.template"       = "s3://${local.bucket}/readings/dt=$${dt}/"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${local.bucket}/readings/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "ignore.malformed.json" = "true"
      }
    }

    columns {
      name = "timestamp"
      type = "string"
    }
    columns {
      name = "temperature_c"
      type = "double"
    }
    columns {
      name = "humidity_percent"
      type = "double"
    }
    columns {
      name = "vpd_kpa"
      type = "double"
    }
    columns {
      name = "controller_vpd_kpa"
      type = "double"
    }
    columns {
      name = "probe_temperature_c"
      type = "double"
    }
    columns {
      name = "probe_humidity_percent"
      type = "double"
    }
    columns {
      name = "co2_ppm"
      type = "double"
    }
    columns {
      name = "source"
      type = "string"
    }
    columns {
      name = "host"
      type = "string"
    }
  }
}

resource "aws_athena_workgroup" "telemetry" {
  name          = "grow-room-telemetry"
  force_destroy = true
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 1073741824   # 1 GB hard stop per query
    publish_cloudwatch_metrics_enabled = true
    result_configuration {
      output_location = "s3://${local.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.telemetry.arn
      }
    }
  }
}

# ---------- home PC identity: IAM Roles Anywhere ----------
resource "aws_rolesanywhere_trust_anchor" "home" {
  name    = "grow-room-home-ca"
  enabled = true
  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data {
      x509_certificate_data = file(var.ca_cert_file)
    }
  }
}

data "aws_iam_policy_document" "shipper_trust" {
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
      values   = ["grow-room-home-shipper"]
    }
  }
}

resource "aws_iam_role" "shipper" {
  name                 = "grow-room-home-shipper"
  assume_role_policy   = data.aws_iam_policy_document.shipper_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "shipper" {
  statement {
    sid       = "WriteReadingsOnly"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.telemetry.arn}/readings/*"]
  }
  statement {
    sid       = "EncryptWithTelemetryKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.telemetry.arn]
  }
}

resource "aws_iam_role_policy" "shipper" {
  name   = "put-readings"
  role   = aws_iam_role.shipper.id
  policy = data.aws_iam_policy_document.shipper.json
}

resource "aws_rolesanywhere_profile" "home" {
  name             = "grow-room-home"
  enabled          = true
  role_arns        = [aws_iam_role.shipper.arn]
  duration_seconds = 3600
}

output "bucket" { value = aws_s3_bucket.telemetry.bucket }
output "workgroup" { value = aws_athena_workgroup.telemetry.name }
output "trust_anchor_arn" { value = aws_rolesanywhere_trust_anchor.home.arn }
output "profile_arn" { value = aws_rolesanywhere_profile.home.arn }
output "role_arn" { value = aws_iam_role.shipper.arn }