output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "List of public subnet IDs (stable sort by AZ key)."
  value       = [for k, s in aws_subnet.public : s.id]
}

output "private_subnet_ids" {
  description = "List of private subnet IDs (stable sort by AZ key)."
  value       = [for k, s in aws_subnet.private : s.id]
}

output "nat_gateway_id" {
  description = "NAT Gateway ID when enabled; otherwise null."
  value       = try(aws_nat_gateway.this[0].id, null)
}

output "availability_zones" {
  description = "AZs used for subnets."
  value       = local.azs
}
