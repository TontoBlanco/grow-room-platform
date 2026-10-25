variable "project_name" {
  description = "Short name used in resource naming and default tags."
  type        = string
  default     = "grow-room"
}

variable "environment" {
  description = "Environment label (dev, staging, prod). Affects naming."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region for resources when enable_eks / AWS path is used."
  type        = string
  default     = "us-west-2"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "az_count" {
  description = "How many availability zones to spread public/private subnets across (2 or 3)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "enable_nat_gateway" {
  description = "Create a NAT gateway for private-subnet egress. Costs money; leave false for daily study."
  type        = bool
  default     = false
}

variable "cluster_mode" {
  description = <<-EOT
    Where the Kubernetes control plane lives for this environment:
      - local : no AWS cluster resources; outputs describe a k3d/kind workflow
      - eks   : create EKS-ready IAM + security group stubs (week 2); full EKS in week 3
  EOT
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "eks"], var.cluster_mode)
    error_message = "cluster_mode must be \"local\" or \"eks\"."
  }
}

variable "enable_eks" {
  description = "Alias-style gate used by the cluster module. Prefer cluster_mode; kept for clarity in guides."
  type        = bool
  default     = false
}

variable "kubernetes_version" {
  description = "Target Kubernetes version string (documented for EKS; informational for local/k3d)."
  type        = string
  default     = "1.31"
}
