data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # 10.60.0.0/16 ->
  #   private  /19 each: 10.60.0.0, 10.60.32.0, 10.60.64.0   (8k IPs each: pods get VPC IPs)
  #   public   /24 each: 10.60.96.0, 10.60.97.0, 10.60.98.0  (ALB + NAT only)
  #   database /24 each: 10.60.100.0, 10.60.101.0, 10.60.102.0
  private_cidrs = { for i, az in local.azs : az => cidrsubnet(var.cidr, 3, i) }
  public_cidrs  = { for i, az in local.azs : az => cidrsubnet(var.cidr, 8, 96 + i) }
  db_cidrs      = { for i, az in local.azs : az => cidrsubnet(var.cidr, 8, 100 + i) }
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # required for interface endpoints' private DNS
  tags                 = { Name = "${var.name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-igw" }
}

# ---------- Subnets ----------
resource "aws_subnet" "public" {
  for_each          = local.public_cidrs
  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value
  tags = {
    Name                     = "${var.name}-public-${each.key}"
    "kubernetes.io/role/elb" = "1" # LB Controller puts internet-facing ALBs here
  }
}

resource "aws_subnet" "private" {
  for_each          = local.private_cidrs
  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value
  tags = {
    Name                              = "${var.name}-private-${each.key}"
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = var.cluster_name # Karpenter launches nodes here
  }
}

resource "aws_subnet" "db" {
  for_each          = local.db_cidrs
  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = { Name = "${var.name}-db-${each.key}" }
}

# ---------- Public routing ----------
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-public-rt" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# ---------- One NAT gateway per AZ (no cross-AZ single point of failure) ----------
resource "aws_eip" "nat" {
  for_each   = local.public_cidrs
  domain     = "vpc"
  tags       = { Name = "${var.name}-nat-eip-${each.key}" }
  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  for_each      = aws_subnet.public
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = each.value.id
  tags          = { Name = "${var.name}-nat-${each.key}" }
}

resource "aws_route_table" "private" {
  for_each = aws_nat_gateway.this
  vpc_id   = aws_vpc.this.id
  tags     = { Name = "${var.name}-private-rt-${each.key}" }
}

resource "aws_route" "private_nat" {
  for_each               = aws_nat_gateway.this
  route_table_id         = aws_route_table.private[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = each.value.id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id # same-AZ NAT
}

# ---------- Database subnets: no internet route at all ----------
resource "aws_route_table" "db" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-db-rt" }
}

resource "aws_route_table_association" "db" {
  for_each       = aws_subnet.db
  subnet_id      = each.value.id
  route_table_id = aws_route_table.db.id
}

# ---------- VPC endpoints ----------
# S3 gateway endpoint: free; S3 traffic (incl. ECR image layers) skips NAT charges.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.private : rt.id]
  tags              = { Name = "${var.name}-s3-gw" }
}

resource "aws_security_group" "endpoints" {
  name        = "${var.name}-vpce"
  description = "HTTPS from inside the VPC to interface endpoints"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  security_group_id = aws_security_group.endpoints.id
  cidr_ipv4         = var.cidr
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# ECR API + Docker registry endpoints: image pulls stay on the AWS network.
resource "aws_vpc_endpoint" "ecr" {
  for_each            = toset(["ecr.api", "ecr.dkr"])
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  tags                = { Name = "${var.name}-${each.key}" }
}

# ---------- Flow logs -> CloudWatch Logs ----------
resource "aws_cloudwatch_log_group" "flow" {
  name              = "/vpc/${var.name}/flow-logs"
  retention_in_days = var.flow_log_retention_days
  kms_key_id        = var.flow_log_kms_key_arn
}

data "aws_iam_policy_document" "flow_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow" {
  name               = "${var.name}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_trust.json
}

resource "aws_iam_role_policy" "flow" {
  role = aws_iam_role.flow.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow.arn}:*"
    }]
  })
}

resource "aws_flow_log" "this" {
  vpc_id          = aws_vpc.this.id
  traffic_type    = "ALL"
  iam_role_arn    = aws_iam_role.flow.arn
  log_destination = aws_cloudwatch_log_group.flow.arn
}