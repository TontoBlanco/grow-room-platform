locals {
  name         = "grow-room-poc"
  cluster_name = "grow-room-poc"
  account_id   = "590183769702"
  app_fqdn     = "${var.app_subdomain}.${var.domain}"
}

module "vpc" {
  source       = "./modules/vpc"
  name         = local.name
  cidr         = var.vpc_cidr
  az_count     = 3
  region       = var.region
  cluster_name = local.cluster_name

  flow_log_kms_key_arn = module.kms_logs.arn
}