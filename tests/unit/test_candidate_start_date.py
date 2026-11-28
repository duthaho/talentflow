from datetime import date, timedelta

import pytest

from app.modules.candidates.domain.start_date import validate_start_date


def test_dates():
    today = date(2026, 1, 1)
    for value in (None, today, today + timedelta(days=365)):
        validate_start_date("hired", value, today)
    for value in (today - timedelta(days=1), today + timedelta(days=366)):
        with pytest.raises(ValueError):
            validate_start_date("hired", value, today)
    with pytest.raises(ValueError):
        validate_start_date("screening", today, today)
