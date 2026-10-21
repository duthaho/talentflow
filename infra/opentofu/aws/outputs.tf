output "attachment_bucket_name" {
  description = "Private S3 bucket for attachment objects. Configure application storage only after the S3 adapter is implemented."
  value       = aws_s3_bucket.attachments.bucket
}

output "ecr_repository_url" {
  description = "Immutable image repository used by a later delivery workflow."
  value       = aws_ecr_repository.application.repository_url
}

output "github_actions_deploy_role_arn" {
  description = "OIDC-trusted role. It intentionally has no permissions until the deployment policy is reviewed."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "runtime_secret_arn" {
  description = "Empty secret container. Populate values out-of-band; never create a secret version through OpenTofu."
  value       = aws_secretsmanager_secret.runtime.arn
}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "private_subnet_ids" {
  value = [for zone in var.availability_zones : aws_subnet.private[zone].id]
}

output "application_log_group_name" {
  value = aws_cloudwatch_log_group.application.name
}
