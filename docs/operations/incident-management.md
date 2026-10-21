# Incident management policy

## Scope

This policy governs production incidents for the TalentFlow API, scheduled workers, managed dependencies, delivery pipeline, and security controls. It supplements the deployment and backup/restore runbooks. It does not replace an organization-wide legal, privacy, or security-incident process.

## Activation

An incident is declared when a production condition meets SEV-1 or SEV-2 criteria in [Phase 0 foundation](phase-0-foundation.md). Any responder may declare an incident; waiting for certainty is not required when customer or data impact is plausible.

The first responder assigns or requests an incident commander, opens the designated incident channel, records UTC start time, severity, affected services/environments, customer impact, and the current hypothesis. Do not copy candidate data, credentials, authorization headers, raw JWTs, feed URLs, or attachment content into chat, tickets, traces, or status updates.

## First response checklist

1. Confirm scope using health, readiness, deployment, dependency, and telemetry evidence.
2. Stop unsafe automation or worker schedules only when this reduces harm; preserve outbox, audit, and delivery evidence.
3. Stabilize first: rollback a compatible image, scale known-good capacity, fail over a dependency, or disable the affected integration through an approved configuration change.
4. Record each action, actor, and UTC time in the incident timeline.
5. Update stakeholders at the declared cadence even when no new root-cause finding exists.
6. Escalate suspected data exposure to the security/privacy owner immediately. Preserve evidence and follow the organization's notification and legal requirements.

## Communication expectations

- **SEV-1:** update internal stakeholders every 30 minutes until stable; publish external status through the designated customer channel when customer impact is confirmed.
- **SEV-2:** update internal stakeholders at least every 60 minutes; external communication is decided by the incident commander and product owner.
- **SEV-3/4:** normal ticket workflow unless impact increases.

Messages state impact, scope, current mitigation, next update time, and known workaround. They do not speculate about root cause or expose sensitive data.

## Closure and follow-up

An incident is resolved only after customer impact is stopped, monitoring is stable for an appropriate observation period, and any paused worker/integration has been safely re-enabled. The incident commander records end time, impact, root cause or current unknowns, remediation owner, and due dates.

Create a blameless review for all SEV-1/2 incidents within five business days. Include timeline, detection gap, contributing factors, customer impact, decisions, follow-up actions, and verification criteria. Track corrective work to closure. Do not treat a post-incident document as proof that the same alert/runbook is effective; exercise the changed control.

## Alert quality requirements

A production paging alert must include a stable deduplication key, severity, service/environment, owner, dashboard link, runbook link, and telemetry query. It pages only for actionable user-impacting conditions: multi-window SLO burn, sustained availability loss, all replicas unready, managed dependency failure, user-impacting queue backlog, backup/restore failure, or confirmed security signal.

Deploy success/failure, rollback, vulnerability findings, capacity trends, elevated client errors, certificate expiry, and worker zero-progress route to ticket/chat by default. They become pages only after an approved impact-based rule exists.
