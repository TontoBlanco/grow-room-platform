module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = local.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnet_ids # nodes + control-plane ENIs stay private

  # API endpoint: private for nodes, public ONLY from your home IP for kubectl
  endpoint_private_access      = true
  endpoint_public_access       = true
  endpoint_public_access_cidrs = [var.my_ip_cidr]

  enabled_log_types                      = ["api", "audit", "authenticator"]
  cloudwatch_log_group_kms_key_id        = module.kms_logs.arn
  cloudwatch_log_group_retention_in_days = 1

  # Envelope-encrypt Kubernetes Secrets with our own key (the module would otherwise make one)
  create_kms_key = false
  encryption_config = {
    provider_key_arn = module.kms_eks.arn
    resources        = ["secrets"]
  }

  # Explicit admin = your SSO role (works no matter who ran apply: you or CI)
  enable_cluster_creator_admin_permissions = false
  access_entries = {
    cole = {
      principal_arn = var.admin_principal_arn
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }

  addons = {
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    kube-proxy             = {}
    coredns                = {}
  }

  # Small, stable "system" node group: runs Karpenter, CoreDNS, controllers.
  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["t3.large"]
      min_size       = 3
      max_size       = 4
      desired_size   = 3 # one per AZ

      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 20
            volume_type           = "gp3"
            encrypted             = true
            kms_key_id            = module.kms_ebs.arn
            delete_on_termination = true
          }
        }
      }
    }
  }

  # Karpenter finds the node security group by this tag
  node_security_group_tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }
}

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "21.29.0"

  cluster_name                    = module.eks.cluster_name
  create_pod_identity_association = true # SA kube-system/karpenter
  node_iam_role_use_name_prefix   = false
  node_iam_role_name              = "${local.name}-karpenter-node"
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}