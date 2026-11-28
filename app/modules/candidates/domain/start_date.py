"""Recruiting owns validation of the optional date supplied when hiring."""

from datetime import date, timedelta


def validate_start_date(target: str, value: date | None, today: date) -> None:
    if value is not None and (
        target != "hired" or not today <= value <= today + timedelta(days=365)
    ):
        raise ValueError(
            "start_date requires hired and must be within today through today +365 UTC"
        )
