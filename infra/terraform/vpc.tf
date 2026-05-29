module "vpc" {
  source = "terraform-aws-modules/vpc/aws"
  version = "5.5.0"
  name = "${var.name}-vpc"
  cidr = "10.20.0.0/16"
  azs              = ["${var.region}a", "${var.region}b"]
  private_subnets  = ["10.20.1.0/24", "10.20.2.0/24"]
  public_subnets   = ["10.20.101.0/24", "10.20.102.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
  tags = var.tags
}

output "vpc_id"          { value = module.vpc.vpc_id }
output "private_subnets" { value = module.vpc.private_subnets }
