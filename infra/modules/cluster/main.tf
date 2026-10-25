# Cluster module (Week 2):
#   local -> no AWS resources; outputs a k3d create command and metadata
#   eks   -> security group + IAM role stubs ready for an aws_eks_cluster in Week 3
#
# Full managed node groups / Fargate come later. Week 2 proves you can author
# the supporting IAM and network attachment pieces from scratch.

locals {
  is_eks       = var.cluster_mode == "eks"
  cluster_name = "${var.name_prefix}-cluster"
  k3d_name     = replace(var.name_prefix, "_", "-")
}

# --- EKS-ready security group (control plane ENIs) ---

resource "aws_security_group" "cluster" {
  count = local.is_eks ? 1 : 0

  name        = "${local.cluster_name}-sg"
  description = "EKS control-plane security group stub for ${local.cluster_name}"
  vpc_id      = var.vpc_id

  # API server access from within the VPC (tighten later for private-only API).
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Week 3: replace with VPC CIDR or bastion SG
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.cluster_name}-sg"
  }
}

# --- IAM role the EKS control plane will assume ---

data "aws_iam_policy_document" "eks_assume_role" {
  count = local.is_eks ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  count = local.is_eks ? 1 : 0

  name               = "${local.cluster_name}-role"
  assume_role_policy = data.aws_iam_policy_document.eks_assume_role[0].json

  tags = {
    Name = "${local.cluster_name}-role"
  }
}

resource "aws_iam_role_policy_attachment" "cluster_AmazonEKSClusterPolicy" {
  count = local.is_eks ? 1 : 0

  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster[0].name
}

resource "aws_iam_role_policy_attachment" "cluster_AmazonEKSVPCResourceController" {
  count = local.is_eks ? 1 : 0

  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
  role       = aws_iam_role.cluster[0].name
}

# Week 3 will add:
#   resource "aws_eks_cluster" "this" { ... }
# using aws_iam_role.cluster[0].arn, aws_security_group.cluster[0].id,
# and subnet IDs from the network module.
