# =============================================================================
# Cloud Parity Reference: AWS EKS (ARM64 Graviton) Mapping
#
# 로컬 Mac M4 Max(local-m4)에서 운영 중인 동일한 platform/gitops 및
# apps/order-service/k8s/overlays/cloud-eks 매니페스트를 AWS EKS로
# 이식할 때 사용하는 Terraform 참조 골격이다. (실제 과금 방지를 위해 로컬에서는 미실행)
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.5"

  name = "${var.cluster_name}-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.aws_region}a", "${var.aws_region}c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.8"

  cluster_name    = var.cluster_name
  cluster_version = "1.32"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    arm64_core = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = ["t4g.xlarge"]
      min_size       = 3
      max_size       = 5
      desired_size   = 3
    }
  }
}

resource "aws_s3_bucket" "backups" {
  bucket_prefix = "${var.cluster_name}-dr-backups-"
}

resource "aws_ecr_repository" "order_service" {
  name                 = "apps/order-service"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}
