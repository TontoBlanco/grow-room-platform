output "cluster_mode" {
  description = "Active mode: local or eks."
  value       = var.cluster_mode
}

output "cluster_name" {
  description = "Logical cluster name."
  value       = local.cluster_name
}

output "cluster_security_group_id" {
  description = "Control-plane SG ID when eks; null when local."
  value       = try(aws_security_group.cluster[0].id, null)
}

output "cluster_role_arn" {
  description = "EKS control-plane IAM role ARN when eks; null when local."
  value       = try(aws_iam_role.cluster[0].arn, null)
}

output "kubernetes_version" {
  description = "Target Kubernetes version."
  value       = var.kubernetes_version
}

output "k3d_create_command" {
  description = "Copy-paste command to create a local k3d cluster for daily work."
  value       = "k3d cluster create ${local.k3d_name} --agents 2 --port \"8080:80@loadbalancer\" --port \"8443:443@loadbalancer\""
}

output "subnet_ids_for_eks" {
  description = "Suggested subnet IDs for a future aws_eks_cluster (private preferred)."
  value = {
    private = var.private_subnet_ids
    public  = var.public_subnet_ids
  }
}
