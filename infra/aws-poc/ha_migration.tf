# Phase 8 cluster pieces. count is zero unless enable_ha_migration is true,
# which scripts/aws-poc.ps1 sets only for `up -WithHA`. A plain up plan does
# not create these resources.
#
# The backup role itself lives in infra/telemetry (it has to outlive this
# cluster). This file only attaches that role to the home-assistant service
# account and gives the nodes a volume driver so the restored config survives
# a pod restart during the session.

module "ebs_csi_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"
  count   = var.enable_ha_migration ? 1 : 0

  name                      = "${local.name}-ebs-csi"
  attach_aws_ebs_csi_policy = true
  aws_ebs_csi_kms_arns      = [module.kms_ebs.arn]
}

resource "aws_eks_addon" "ebs_csi" {
  count                       = var.enable_ha_migration ? 1 : 0
  cluster_name                = module.eks.cluster_name
  addon_name                  = "aws-ebs-csi-driver"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  pod_identity_association {
    role_arn        = module.ebs_csi_pod_identity[0].iam_role_arn
    service_account = "ebs-csi-controller-sa"
  }
}

resource "aws_iam_role_policy_attachment" "system_node_ebs_csi" {
  count      = var.enable_ha_migration ? 1 : 0
  role       = module.eks.eks_managed_node_groups["system"].iam_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_iam_role_policy_attachment" "karpenter_node_ebs_csi" {
  count      = var.enable_ha_migration ? 1 : 0
  role       = module.karpenter.node_iam_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_pod_identity_association" "ha_backup" {
  count           = var.enable_ha_migration ? 1 : 0
  cluster_name    = module.eks.cluster_name
  namespace       = "grow-room"
  service_account = "home-assistant"
  role_arn        = "arn:aws:iam::${local.account_id}:role/grow-room-ha-backup"
}
