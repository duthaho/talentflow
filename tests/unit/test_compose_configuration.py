"""Regression checks for local Compose runtime configuration."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_keycloak_healthcheck_allows_first_start_augmentation() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())

    assert compose["services"]["keycloak"]["healthcheck"]["start_period"] == "8m"
