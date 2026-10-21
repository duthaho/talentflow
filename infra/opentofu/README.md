# TalentFlow AWS OpenTofu foundation

This directory establishes the reviewed AWS foundation selected for TalentFlow:

- **Runtime target:** ECS Fargate in a dedicated AWS account per environment.
- **Observability target:** Sentry for application error tracking and Datadog for metrics, logs, traces, dashboards, and alert routing. Workload telemetry remains OpenTelemetry/OTLP based.
- **Paging:** PagerDuty for actionable pages; the team chat workspace remains a deployment-time configuration, not repository data.
- **State:** encrypted, versioned, private S3 state using native S3 lock files. The state bucket is created from `bootstrap/` exactly once per approved account/region.

The foundation deliberately does **not** deploy a running application, RDS instance, Redis cluster, or ECS service yet. Those workloads require reviewed capacity, domain, certificate, database, network-egress, secret, Datadog, Sentry, and PagerDuty values. No credentials, DSNs, webhook URLs, or customer data belong in this directory.

## Layout

- `bootstrap/`: creates only the state bucket. Apply it with an organization-controlled operator identity; it cannot use the state backend it creates.
- `aws/`: creates the provider-neutral platform boundary in AWS: VPC/subnets, VPC Flow Logs, private attachment S3 bucket, immutable/scanned ECR repository, CloudWatch log groups, an empty runtime-secret container, and a GitHub OIDC-trusted deployment role.
- `.opentofu-version`: pinned local/CI OpenTofu version.

The OIDC deployment role intentionally has no permissions attached. Phase 3 attaches a narrowly reviewed deployment policy after the ECS, ECR, Secrets Manager, and observability integration contract exists. An empty trusted role is safer than pre-authorizing a broad deployment principal.

## Bootstrap state

1. Use the organization break-glass/bootstrap identity in the target AWS account, not a developer access key stored locally.
2. Copy values into a local, ignored `.tfvars` file. Choose a globally unique bucket name and organization tags.
3. In `bootstrap/`, run `tofu init`, `tofu plan`, and have a second operator review the plan before `tofu apply`.
4. Record the approved bucket name, region, account ID, operator, plan digest, and UTC time in the change record.
5. Restrict state-bucket access to the platform provisioning role and enable the organization’s audit trail. Do not place state in a shared development account.

## Configure an environment

1. Copy `aws/terraform.tfvars.example` to a local `terraform.tfvars`; it is intentionally ignored by Git.
2. Assign a separate AWS account to `staging` and `production`. Do not use production credentials or state for staging.
3. Choose two approved availability zones and a non-overlapping VPC CIDR.
4. Initialize with the bootstrapped state location. Native state locking is enabled by setting `use_lockfile = true` in the local backend config. Example only—replace every placeholder outside Git:

   ```bash
   tofu -chdir=aws init \
     -backend-config="bucket=<state-bucket>" \
     -backend-config="key=talentflow/<environment>/platform.tfstate" \
     -backend-config="region=<aws-region>" \
     -backend-config="use_lockfile=true"
   tofu -chdir=aws plan -out=tfplan
   ```

5. A second reviewer checks the plan, especially CIDRs, account, region, environment tags, public-access blocks, and the GitHub OIDC trust subject. Apply only from the protected deployment path after Phase 3 CI/CD exists.

## Validation

Run without AWS credentials for syntax and provider-schema validation:

```bash
tofu fmt -check -recursive infra/opentofu
tofu -chdir=infra/opentofu/bootstrap init -backend=false
tofu -chdir=infra/opentofu/bootstrap validate
tofu -chdir=infra/opentofu/aws init -backend=false
tofu -chdir=infra/opentofu/aws validate
```

`validate` proves syntax and downloaded provider schemas only. It does not prove an AWS plan, account permissions, costs, network reachability, or deployment success. The CI workflow runs this non-mutating validation on every infrastructure change.
