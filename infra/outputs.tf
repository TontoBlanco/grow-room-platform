output "vpc_id" {
  description = "ID of the VPC created by the network module."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (ingress, load balancers)."
  value       = module.network.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs (workloads when NAT is enabled)."
  value       = module.network.private_subnet_ids
}

output "cluster_mode" {
  description = "Active cluster mode from variables (local or eks)."
  value       = module.cluster.cluster_mode
}

output "cluster_name" {
  description = "Logical cluster name for k3d or EKS."
  value       = module.cluster.cluster_name
}

output "cluster_security_group_id" {
  description = "Security group ID when cluster_mode=eks; null for local."
  value       = module.cluster.cluster_security_group_id
}

output "cluster_role_arn" {
  description = "IAM role ARN for the EKS control plane when cluster_mode=eks; null for local."
  value       = module.cluster.cluster_role_arn
}

output "k3d_create_command" {
  description = "Suggested k3d create command for local daily work."
  value       = module.cluster.k3d_create_command
}

output "budget_reminder" {
  description = "Friendly reminder: set an AWS Budgets alert before any paid apply."
  value       = "Create an AWS Budgets alert at $20/month before terraform apply with enable_nat_gateway or cluster_mode=eks."
}
