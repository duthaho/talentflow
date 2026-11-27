"""Rewrap encrypted webhook keys; retain old KEKs until this completes."""

import app.shared.models  # noqa: F401
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.maintenance import rewrap_batch
from app.shared.database import build_session_factory
from app.shared.settings import settings


def main():
    sessions = build_session_factory(settings.database_url)
    try:
        with sessions() as session:
            while rewrap_batch(
                session, build_cipher(settings), settings.retention_worker_batch_size
            ):
                pass
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
