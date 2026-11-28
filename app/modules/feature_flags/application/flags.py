"""ADR-010 registry and framework-free policy; keys never escape to clients."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Flag:
    key: str
    fallback: bool = False
    scope: Literal["tenant", "request"] = "tenant"
    retired: bool = False


WEBHOOKS_OUTBOUND = Flag("release.webhooks.outbound")
WEBHOOKS_DELIVERY = Flag("ops.webhooks.delivery")
REGISTRY = (WEBHOOKS_OUTBOUND, WEBHOOKS_DELIVERY)


@dataclass(frozen=True)
class Context:
    tenant_id: str
    role: str | None = None


@dataclass(frozen=True)
class Evaluation:
    enabled: bool
    error: bool = False


class FeatureFlags(Protocol):
    def is_enabled(self, flag: Flag, context: Context) -> bool: ...
    def evaluate(self, flag: Flag, context: Context) -> Evaluation: ...


@dataclass(frozen=True)
class WebhooksState:
    enabled: bool
    delivery_paused: bool
    reason: str


def webhooks_state(flags: FeatureFlags, context: Context) -> WebhooksState:
    release = flags.evaluate(WEBHOOKS_OUTBOUND, context)
    delivery = flags.evaluate(WEBHOOKS_DELIVERY, context)
    return WebhooksState(
        release.enabled,
        not (release.enabled and delivery.enabled),
        "flag_error" if release.error or delivery.error else "flag_off",
    )
