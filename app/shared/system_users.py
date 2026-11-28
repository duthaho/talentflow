from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_system_users(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO users (id, email, created_at) VALUES ('system:careers', NULL, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
        )
    )
    session.commit()
