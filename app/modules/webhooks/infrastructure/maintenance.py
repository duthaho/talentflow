"""Bounded expiration, retention and KEK rewrap transactions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select, update

from app.modules.webhooks.application.signing import aad
from app.modules.webhooks.infrastructure.models import (
    Attempt,
    Delivery,
    Endpoint,
    Event,
    Secret,
    Subscription,
)


def expire_secrets(session, batch_size):
    rows = list(
        session.scalars(
            select(Secret)
            .where(Secret.status == "previous", Secret.expires_at <= datetime.now(UTC))
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.status, row.ciphertext = "expired", None
    session.commit()
    return len(rows)


def rewrap_batch(session, cipher, batch_size):
    rows = list(
        session.scalars(
            select(Secret)
            .where(Secret.ciphertext.is_not(None), Secret.key_id != cipher.active)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        context = aad(row.tenant_id, row.endpoint_id, row.id)
        row.ciphertext = cipher.encrypt(cipher.decrypt(row.ciphertext, context), context)
        row.key_id = cipher.active
    session.commit()
    return len(rows)


def purge_webhooks(session, *, batch_size, retention_days=30):
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    rows = list(
        session.execute(
            select(Delivery.tenant_id, Delivery.id)
            .where(Delivery.status != "pending", Delivery.completed_at < cutoff)
            .order_by(Delivery.completed_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for tenant, ident in rows:
        session.execute(
            delete(Attempt).where(Attempt.tenant_id == tenant, Attempt.delivery_id == ident)
        )
        # Explicitly handles SQLite test engines with foreign_keys off too.
        session.execute(
            update(Delivery)
            .where(Delivery.tenant_id == tenant, Delivery.redelivery_of_id == ident)
            .values(redelivery_of_id=None)
        )
        session.execute(delete(Delivery).where(Delivery.tenant_id == tenant, Delivery.id == ident))
    # Orphan bodies and tombstones are independently bounded; don't touch leased work.
    events = list(
        session.scalars(
            select(Event)
            .where(
                ~exists(
                    select(Delivery.id).where(
                        Delivery.tenant_id == Event.tenant_id, Delivery.event_id == Event.event_id
                    )
                )
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for event in events:
        session.delete(event)
    endpoints = list(
        session.scalars(
            select(Endpoint)
            .where(
                Endpoint.status == "deleted",
                ~exists(
                    select(Delivery.id).where(
                        Delivery.tenant_id == Endpoint.tenant_id,
                        Delivery.endpoint_id == Endpoint.id,
                    )
                ),
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for endpoint in endpoints:
        for model in (Secret, Subscription):
            session.execute(
                delete(model).where(
                    model.tenant_id == endpoint.tenant_id, model.endpoint_id == endpoint.id
                )
            )
        session.delete(endpoint)
    session.commit()
    return len(rows)
