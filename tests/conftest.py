"""Existing workflow tests explicitly run with both capabilities on, offline.

Flag behavior tests supply their own file or RPC settings. No production bypass.
"""

import os
from pathlib import Path

import pytest

os.environ["FEATURE_FLAGS_PROVIDER"] = "file"
os.environ["FLAGD_OFFLINE_FLAG_SOURCE_PATH"] = str(Path(__file__).parent / "fixtures/flags-on.json")


@pytest.fixture
def feature_flags():
    from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
    from app.shared.settings import Settings

    adapter = OpenFeatureFlags(Settings())
    try:
        yield adapter
    finally:
        adapter.close()
