"""The only SDK boundary. Pinned flagd 0.6.1 RPC or real offline JsonLogic."""

import logging
import threading
import time
from uuid import uuid4

import grpc
from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider
from openfeature.contrib.provider.flagd.config import CacheType, ResolverType
from openfeature.contrib.provider.flagd.resolvers.grpc import GrpcResolver
from openfeature.evaluation_context import EvaluationContext
from openfeature.hook import Hook
from opentelemetry import trace
from prometheus_client import Counter

from app.modules.feature_flags.application.flags import Context, Evaluation, Flag

logger = logging.getLogger(__name__)
evaluations = Counter(
    "talentflow_feature_flag_evaluations_total",
    "Feature evaluations",
    ["flag_key", "variant", "reason"],
)


class EvaluationHook(Hook):
    def __init__(self):
        self.warned = {}
        self.lock = threading.Lock()

    def finally_after(self, hook_context, details, hints):
        # Only bounded enum/registry values: never include context or provider messages.
        reason = str(getattr(details.reason, "value", details.reason) or "UNKNOWN")
        variant = details.variant if details.variant in ("on", "off") else "off"
        attributes = {
            "feature_flag.key": hook_context.flag_key,
            "feature_flag.result.variant": variant,
            "feature_flag.result.reason": reason,
            "feature_flag.provider.name": "flagd",
        }
        error_code = details.error_code
        if error_code:
            attributes["error.type"] = str(getattr(error_code, "value", error_code))
            now = time.monotonic()
            with self.lock:
                warn = now - self.warned.get(hook_context.flag_key, float("-inf")) >= 60
                if warn:
                    self.warned[hook_context.flag_key] = now
            if warn:
                logger.warning(
                    "feature_flag_evaluation_failed",
                    extra={
                        "flag_key": hook_context.flag_key,
                        "error_code": attributes["error.type"],
                        "reason": reason,
                    },
                )
        evaluations.labels(hook_context.flag_key, variant, reason).inc()
        trace.get_current_span().add_event("feature_flag.evaluation", attributes)


class NoRetryResolver(GrpcResolver):
    def _generate_channel(self, config):
        # The pinned provider otherwise installs a three-attempt retry policy.
        options = [("grpc.enable_retries", 0)]
        target = f"{config.host}:{config.port}"
        if config.tls:
            return grpc.secure_channel(target, grpc.ssl_channel_credentials(), options=options)
        return grpc.insecure_channel(target, options=options)


class NoRetryProvider(FlagdProvider):
    def __init__(self, **options):
        self.lifecycle_lock = threading.Lock()
        self.closed = False
        super().__init__(**options)

    def initialize(self, evaluation_context):
        with self.lifecycle_lock:
            if not self.closed:
                super().initialize(evaluation_context)

    def shutdown(self):
        with self.lifecycle_lock:
            if self.closed:
                return
            self.closed = True
            super().shutdown()
        # Upstream shutdown signals but does not join its owned watchers.
        resolver = self.resolver
        owner = getattr(resolver, "connector", resolver)
        for name in ("monitor_thread", "thread", "timer"):
            thread = getattr(owner, name, None)
            if thread and thread is not threading.current_thread():
                thread.join(timeout=1)

    def setup_resolver(self):
        if self.config.resolver != ResolverType.RPC:
            return super().setup_resolver()
        return NoRetryResolver(
            self.config,
            self.emit_provider_ready,
            self.emit_provider_error,
            self.emit_provider_stale,
            self.emit_provider_configuration_changed,
        )


class OpenFeatureFlags:
    def __init__(self, settings):
        self.domain = f"talentflow-{uuid4()}"
        file_mode = settings.feature_flags_provider == "file"
        self.provider = NoRetryProvider(
            host=settings.flagd_host,
            port=settings.flagd_port,
            tls=settings.flagd_tls,
            deadline_ms=settings.flagd_deadline_ms,
            cache=CacheType.DISABLED,
            resolver_type=ResolverType.FILE if file_mode else ResolverType.RPC,
            offline_flag_source_path=settings.flagd_offline_flag_source_path if file_mode else None,
            sync_metadata_disabled=True,
        )
        # No blocking RPC startup or readiness dependency. File initialization is local.
        register = api.set_provider_and_wait if file_mode else api.set_provider
        register(self.provider, self.domain)
        self.client = api.get_client(self.domain)
        self.client.add_hooks([EvaluationHook()])

    def evaluate(self, flag: Flag, context: Context) -> Evaluation:
        if flag.retired:
            raise ValueError(f"Retired flag cannot be evaluated: {flag.key}")
        attributes = {"tenant_id": context.tenant_id}
        if flag.scope == "request" and context.role is not None:
            attributes["role"] = context.role
        details = self.client.get_boolean_details(
            flag.key,
            flag.fallback,
            EvaluationContext(targeting_key=context.tenant_id, attributes=attributes),
        )
        return Evaluation(details.value, details.error_code is not None)

    def is_enabled(self, flag: Flag, context: Context) -> bool:
        return self.evaluate(flag, context).enabled

    def close(self):
        self.provider.shutdown()
