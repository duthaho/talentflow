variable "aws_region" {
  description = "AWS region for one isolated TalentFlow environment."
  type        = string
}

variable "environment" {
  description = "Environment name. Each environment uses its own AWS account or an equivalent hard isolation boundary."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "availability_zones" {
  description = "At least two availability zones in aws_region."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least two availability zones are required."
  }
}

variable "vpc_cidr" {
  description = "Non-overlapping RFC1918 CIDR for this environment."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository authorized to assume the future deployment role."
  type        = string
  default     = "duthaho/talentflow"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be owner/repository."
  }
}

variable "attachment_retention_days" {
  description = "S3 lifecycle retention for noncurrent attachment object versions. This does not replace application retention policy."
  type        = number
  default     = 30

  validation {
    condition     = var.attachment_retention_days >= 7
    error_message = "attachment_retention_days must be at least 7."
  }
}

variable "tags" {
  description = "Additional mandatory organization tags such as CostCenter, DataClassification, and Owner."
  type        = map(string)
  default     = {}
}
