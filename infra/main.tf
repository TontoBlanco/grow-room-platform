# Root composition: wires modules together.
# Think of this like a Helm umbrella chart calling subcharts with values.

locals {
  # Prefer explicit cluster_mode; enable_eks=true forces the eks path.
  effective_cluster_mode = var.enable_eks ? "eks" : var.cluster_mode
  name_prefix            = "${var.project_name}-${var.environment}"
}

module "network" {
  source = "./modules/network"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  enable_nat_gateway = var.enable_nat_gateway
  aws_region         = var.aws_region
}

module "cluster" {
  source = "./modules/cluster"

  name_prefix        = local.name_prefix
  cluster_mode       = local.effective_cluster_mode
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids
  kubernetes_version = var.kubernetes_version
}
