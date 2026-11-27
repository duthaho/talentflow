# ADR-008: Anonymous application intake

The public careers API accepts hostile multipart input without an authenticated
actor. Its order is a security boundary: explicit request framing and cap, IP
quota, honeypot, tenant/publication eligibility, fields and consent, hashed-email
quota, file validation and synchronous scan, dedupe, then transactional creation.
No FastAPI File/Form parameters may be added to this route: those would parse
before the framing and quota checks. Both the API and Next count actual bytes.

AttachmentService separates inspection from attachment persistence. Candidates
use a CvIntake port on the same database session. The unique tenant/email insert
flushes before storage; a lost PostgreSQL race rolls back and audits reapplication.
Later persistence failures delete the object. Reapplication never changes the
existing case or consent and discards the scanned CV. The system actor has no
membership: tenant bootstrap rejects every reserved `system:` admin id before
any repository write. Identity rejects every `system:` subject even if misconfigured.

New applications, reapplications and honeypot submissions all return the identical
202 body. The requester accepted the residual timing channel: new applications
still perform storage and more database writes. A minimum response time is a
follow-up, along with scan concurrency limits, IPv6 /64 quotas, proxy slow-body
timeouts and CAPTCHA. Fixed-window limits can permit twice the quota around a
reset boundary. Redis and scanner errors fail closed with 503.

`web/ingress.cjs` captures the socket peer before Next processes headers. Next
16.4 preserves a browser-supplied X-Forwarded-For, so trusting that header by
itself is unsafe. Every supported startup command loads the ingress hook, which
overwrites its private chain header. The server-only clientIp helper selects the
socket by default; CAREERS_TRUSTED_PROXY_HOPS selects an explicitly configured
number of trusted proxies to its left. Never expose a deployment with that count
set unless those proxies overwrite or append the actual peer and are the only
network path to web. Missing or invalid peer metadata fails closed. The public
SSR fetches and apply proxy set a single X-Forwarded-For value. Listing and
consent use a 60-second cache per visitor address; publication changes may take
that long to appear, while API application eligibility is checked immediately.

Compose assigns web 172.29.127.10 and trusts only its /32, excluding the bridge
gateway. In a deployment, the API must be reachable only through web. The local
loopback API port is for development tools, not public ingress. Deploy multiple
stacks on separate hosts or override the subnet and /32 together.

The apply proxy never loads sessions. Its fixed request header allow-list is
content-type, accurate content-length, canonical x-forwarded-for and optional
x-correlation-id. Only status, content-type and retry-after pass back. Same-origin
checks at web and explicit CORS origin validation at the API reject drive-by posts.
ClamAV explicitly alerts on encrypted content and exceeded scan/recursion limits.

Consent comes from the server's versioned template, not submitted text. It renders
as plain text; the exact wording and server timestamp are immutable. Retention
clears only the wording after the normal terminal-state/legal-hold checks. Metrics
have one bounded outcome label; normalized emails are SHA-256 hashed with the
tenant id before entering Redis keys. Names reject control and bidi characters.
