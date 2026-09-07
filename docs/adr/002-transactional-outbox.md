# ADR-002: Transactional Outbox and At-Least-Once Delivery

**Status:** Accepted

## Decision

Business state, audit records, and outbox events are persisted in one database transaction. Background publishers treat delivery as at-least-once; consumers use stable event i...[truncated]