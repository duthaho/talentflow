"""Add tenant-scoped webhook storage (ADR-008)."""

from alembic import op

revision = "d62a001"
down_revision = "d126a001"
branch_labels = None
depends_on = None
SCHEMA = """
CREATE TABLE webhook_endpoints (
  id                         varchar(36)   PRIMARY KEY,
  tenant_id                  varchar(36)   NOT NULL,
  url                        varchar(2048) NOT NULL,
  description                varchar(200),
  status                     varchar(16)   NOT NULL CHECK (status IN ('enabled','disabled','deleted')),
  disabled_reason            varchar(16)   CHECK (disabled_reason IN ('manual','failing','gone')),
  version                    integer       NOT NULL DEFAULT 1,
  consecutive_failures       integer       NOT NULL DEFAULT 0,
  failure_streak_started_at  timestamptz,
  created_by                 varchar(36)   NOT NULL,
  created_at                 timestamptz   NOT NULL,
  updated_at                 timestamptz   NOT NULL,
  deleted_at                 timestamptz,
  UNIQUE (tenant_id, id),
  CHECK ((status = 'disabled') = (disabled_reason IS NOT NULL))
);
CREATE UNIQUE INDEX uq_webhook_endpoints_tenant_url ON webhook_endpoints (tenant_id, url) WHERE status <> 'deleted';
CREATE INDEX ix_webhook_endpoints_tenant_page ON webhook_endpoints (tenant_id, created_at DESC, id DESC);

CREATE TABLE webhook_subscriptions (
  tenant_id    varchar(36)  NOT NULL,
  endpoint_id  varchar(36)  NOT NULL,
  event_type   varchar(160) NOT NULL,
  created_at   timestamptz  NOT NULL,
  PRIMARY KEY (endpoint_id, event_type),
  FOREIGN KEY (tenant_id, endpoint_id) REFERENCES webhook_endpoints (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX ix_webhook_subscriptions_fanout ON webhook_subscriptions (tenant_id, event_type);

CREATE TABLE webhook_secrets (
  id           varchar(36)  PRIMARY KEY,
  tenant_id    varchar(36)  NOT NULL,
  endpoint_id  varchar(36)  NOT NULL,
  status       varchar(16)  NOT NULL CHECK (status IN ('current','previous','expired')),
  ciphertext   text,
  key_id       varchar(64),
  created_at   timestamptz  NOT NULL,
  expires_at   timestamptz,
  FOREIGN KEY (tenant_id, endpoint_id) REFERENCES webhook_endpoints (tenant_id, id) ON DELETE CASCADE,
  CHECK ((status = 'expired') = (ciphertext IS NULL))
);
CREATE UNIQUE INDEX uq_webhook_secrets_current  ON webhook_secrets (endpoint_id) WHERE status = 'current';
CREATE UNIQUE INDEX uq_webhook_secrets_previous ON webhook_secrets (endpoint_id) WHERE status = 'previous';

CREATE TABLE webhook_events (
  tenant_id    varchar(36)  NOT NULL,
  event_id     varchar(36)  NOT NULL,
  event_type   varchar(160) NOT NULL,
  body         jsonb        NOT NULL,
  occurred_at  timestamptz  NOT NULL,
  received_at  timestamptz  NOT NULL,
  PRIMARY KEY (tenant_id, event_id)
);

CREATE TABLE webhook_deliveries (
  id                varchar(36)  PRIMARY KEY,
  tenant_id         varchar(36)  NOT NULL,
  endpoint_id       varchar(36)  NOT NULL,
  event_id          varchar(36)  NOT NULL,
  event_type        varchar(160) NOT NULL,
  status            varchar(16)  NOT NULL CHECK (status IN ('pending','succeeded','dead_lettered','cancelled')),
  attempt_count     integer      NOT NULL DEFAULT 0,
  next_attempt_at   timestamptz,
  leased_until      timestamptz,
  last_attempt_at   timestamptz,
  last_status_code  integer,
  last_error_code   varchar(32),
  kind              varchar(16)  NOT NULL CHECK (kind IN ('fanout','redelivery')),
  redelivery_of_id  varchar(36)  REFERENCES webhook_deliveries (id) ON DELETE SET NULL,
  requested_by      varchar(36),
  created_at        timestamptz  NOT NULL,
  completed_at      timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, endpoint_id) REFERENCES webhook_endpoints (tenant_id, id),
  FOREIGN KEY (tenant_id, event_id)    REFERENCES webhook_events (tenant_id, event_id),
  CHECK (kind = 'redelivery' OR (redelivery_of_id IS NULL AND requested_by IS NULL)),
  CHECK (kind = 'fanout' OR requested_by IS NOT NULL)
);
CREATE UNIQUE INDEX uq_webhook_deliveries_fanout  ON webhook_deliveries (endpoint_id, event_id) WHERE kind = 'fanout';
CREATE UNIQUE INDEX uq_webhook_deliveries_pending ON webhook_deliveries (endpoint_id, event_id) WHERE status = 'pending';
CREATE INDEX ix_webhook_deliveries_due  ON webhook_deliveries (next_attempt_at) WHERE status = 'pending';
CREATE INDEX ix_webhook_deliveries_log  ON webhook_deliveries (tenant_id, endpoint_id, created_at DESC, id DESC);
CREATE INDEX ix_webhook_deliveries_purge ON webhook_deliveries (completed_at) WHERE status <> 'pending';

CREATE TABLE webhook_delivery_attempts (
  id               varchar(36)  PRIMARY KEY,
  tenant_id        varchar(36)  NOT NULL,
  delivery_id      varchar(36)  NOT NULL,
  attempt_number   integer      NOT NULL,
  started_at       timestamptz  NOT NULL,
  duration_ms      integer      NOT NULL,
  status_code      integer,
  error_code       varchar(32),
  signed_secret_ids varchar(80) NOT NULL,
  UNIQUE (delivery_id, attempt_number),
  FOREIGN KEY (tenant_id, delivery_id) REFERENCES webhook_deliveries (tenant_id, id) ON DELETE CASCADE
);
"""


def upgrade():
    sql = SCHEMA
    if op.get_bind().dialect.name == "sqlite":
        sql = sql.replace("jsonb", "JSON").replace("timestamptz", "DATETIME")
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    for table in (
        "webhook_delivery_attempts",
        "webhook_deliveries",
        "webhook_events",
        "webhook_secrets",
        "webhook_subscriptions",
        "webhook_endpoints",
    ):
        op.drop_table(table)
