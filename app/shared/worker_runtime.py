from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any

from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.shared.observability import worker_backlog, worker_last_success, worker_ready

logger = logging.getLogger(__name__)

Cycle = Callable[[], int]
Shutdown = Callable[[], None]


@dataclass
class WorkerStatus:
    live: bool = True
    ready: bool = False


class WorkerProbeServer:
    """Small, dependency-free probe endpoint for a standalone worker process."""

    def __init__(self, status: WorkerStatus, *, host: str, port: int) -> None:
        self._status = status
        self._server = ThreadingHTTPServer((host, port), self._handler())
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        status = self._status

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                if self.path == "/health/live":
                    self._json(200 if status.live else 503)
                elif self.path == "/health/ready":
                    self._json(200 if status.ready else 503)
                elif self.path == "/metrics":
                    body = generate_latest()
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def _json(self, code: int) -> None:
                body = b'{"status":"ok"}' if code == 200 else b'{"status":"unavailable"}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class WorkerLoop:
    """Runs a bounded worker cycle repeatedly and coordinates graceful shutdown."""

    def __init__(
        self,
        *,
        name: str,
        cycle: Cycle,
        readiness_check: Callable[[], None],
        shutdown: Shutdown | None = None,
        poll_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        grace_seconds: float = 30.0,
        probe_host: str = "0.0.0.0",
        probe_port: int = 8001,
        probe_server: WorkerProbeServer | None = None,
    ) -> None:
        self.name = name
        self._cycle = cycle
        self._readiness_check = readiness_check
        self._shutdown = shutdown or (lambda: None)
        self._poll_seconds = poll_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._grace_seconds = grace_seconds
        self._stop = Event()
        self._status = WorkerStatus()
        self._probe_server = probe_server or WorkerProbeServer(
            self._status, host=probe_host, port=probe_port
        )

    def request_stop(self) -> None:
        self._stop.set()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def run(self, *, once: bool = False) -> None:
        self._install_signal_handlers()
        self._probe_server.start()
        try:
            self._readiness_check()
            self._status.ready = True
            worker_ready.labels(self.name).set(1)
            delay = self._poll_seconds
            while not self._stop.is_set():
                try:
                    with trace.get_tracer(__name__).start_as_current_span(
                        "worker.cycle", attributes={"worker.name": self.name}
                    ):
                        backlog = self._cycle()
                except Exception:
                    logger.exception("worker_cycle_failed", extra={"event": "worker_cycle_failed"})
                    delay = min(delay * 2, self._max_backoff_seconds)
                else:
                    worker_backlog.labels(self.name).set(backlog)
                    worker_last_success.labels(self.name).set(time.time())
                    delay = (
                        self._poll_seconds if backlog else min(delay * 2, self._max_backoff_seconds)
                    )
                if once:
                    break
                self._stop.wait(delay)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            self._status.ready = False
            self._status.live = False
            worker_ready.labels(self.name).set(0)
            self._shutdown()
            self._probe_server.close()

    def _install_signal_handlers(self) -> None:
        def stop(signum: int, frame: object) -> None:
            logger.info("worker_shutdown_requested", extra={"event": "worker_shutdown_requested"})
            self.request_stop()

            signal.signal(signal.SIGALRM, self._force_stop)
            signal.setitimer(signal.ITIMER_REAL, self._grace_seconds)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def _force_stop(self, _signum: int, _frame: object) -> None:
        self._shutdown()
        raise SystemExit(0)
