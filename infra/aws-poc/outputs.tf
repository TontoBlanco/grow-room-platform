output "region" { value = var.region }
output "vpc_id" { value = module.vpc.vpc_id }
output "cluster_name" { value = module.eks.cluster_name }
output "karpenter_queue_name" { value = module.karpenter.queue_name }
output "karpenter_node_role" { value = module.karpenter.node_iam_role_name }
output "rds_address" { value = aws_db_instance.audit.address }
output "rds_secret_arn" { value = aws_db_instance.audit.master_user_secret[0].secret_arn }
output "sensor_bucket" { value = aws_s3_bucket.sensor.bucket }
output "certificate_arn" { value = aws_acm_certificate_validation.app.certificate_arn }
output "domain" { value = var.domain }
output "app_fqdn" { value = local.app_fqdn }
output "ebs_kms_key_arn" { value = module.kms_ebs.arn }
output "kms_aliases" {
  value = [for m in [module.kms_eks, module.kms_rds, module.kms_s3, module.kms_secrets, module.kms_logs, module.kms_ebs] : m.alias_name]
}
output "waf_arn" { value = var.enable_waf ? aws_wafv2_web_acl.alb[0].arn : "" }