# Keys come from kms.tf: kms_rds (storage), kms_secrets (password), kms_s3 (buckets)

# ---------- RDS Postgres, Multi-AZ, private ----------
resource "aws_db_subnet_group" "audit" {
  name       = "${local.name}-audit"
  subnet_ids = module.vpc.db_subnet_ids
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "Postgres from EKS nodes/pods only"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_nodes" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = module.eks.node_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_instance" "audit" {
  identifier     = "${local.name}-audit"
  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = module.kms_rds.arn

  db_name  = "audit"
  username = "audit_admin"

  # RDS generates + stores the password in Secrets Manager (no password in tfstate)
  manage_master_user_password   = true
  master_user_secret_kms_key_id = module.kms_secrets.arn

  multi_az               = true # synchronous standby in a second AZ
  db_subnet_group_name   = aws_db_subnet_group.audit.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  backup_retention_period = 1
  skip_final_snapshot     = true # demo: we destroy the same day
  deletion_protection     = false
  apply_immediately       = true
}

# ---------- S3 sensor data + Athena ----------
resource "aws_s3_bucket" "sensor" {
  bucket        = "${local.name}-sensor-${local.account_id}"
  force_destroy = true # lets terraform destroy empty it
}

resource "aws_s3_bucket_public_access_block" "sensor" {
  bucket                  = aws_s3_bucket.sensor.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sensor" {
  bucket = aws_s3_bucket.sensor.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = module.kms_s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket" "athena" {
  bucket        = "${local.name}-athena-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "athena" {
  bucket                  = aws_s3_bucket.athena.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_athena_workgroup" "poc" {
  name          = local.name
  force_destroy = true
  configuration {
    enforce_workgroup_configuration = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena.bucket}/results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = module.kms_s3.arn
      }
    }
  }
}

resource "aws_glue_catalog_database" "sensor" {
  name = "grow_room_poc"
}

# Partition projection: Athena computes dt=YYYY-MM-DD partitions, no crawler needed
resource "aws_glue_catalog_table" "readings" {
  name          = "readings"
  database_name = aws_glue_catalog_database.sensor.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"            = "json"
    "projection.enabled"        = "true"
    "projection.dt.type"        = "date"
    "projection.dt.format"      = "yyyy-MM-dd"
    "projection.dt.range"       = "2026-10-01,NOW"
    "storage.location.template" = "s3://${aws_s3_bucket.sensor.bucket}/raw/dt=$${dt}/"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.sensor.bucket}/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
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
      name = "source"
      type = "string"
    }
  }
}