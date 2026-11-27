"""The production image smoke must use the same disposable KEK in every container."""

import os
import shlex
import subprocess
from pathlib import Path

import yaml

from app.shared.settings import Settings


def test_container_smoke_generates_and_forwards_a_valid_production_keyring(tmp_path):
    job = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())["jobs"]["container-smoke"]
    assert job["env"]["APP_ENV"] == "production"
    generation = next((step for step in job["steps"] if step.get("id") == "webhook-keyring"), None)
    assert generation is not None, "container-smoke must generate a throwaway encryption keyring"
    env_file = tmp_path / "github-env"
    completed = subprocess.run(
        ["bash", "-e", "-c", generation["run"]],
        env={**os.environ, "GITHUB_ENV": str(env_file)},
        capture_output=True,
        text=True,
        check=True,
    )
    variables = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert set(variables) == {"WEBHOOK_SECRET_KEYS", "WEBHOOK_SECRET_ACTIVE_KEY_ID"}
    assert completed.stdout.startswith("::add-mask::"), "Mask the random key before forwarding it"
    config = Settings(
        _env_file=None,
        **{name.lower(): value for name, value in {**job["env"], **variables}.items()},
    )
    assert config.webhook_secret_active_key_id == "ci"
    containers = 0
    for step in job["steps"]:
        run = step.get("run", "")
        if "docker run " not in run:
            continue
        containers += 1
        tokens = shlex.split(run.replace("\\\n", " "))
        forwarded = {
            tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == "--env"
        }
        assert set(variables) <= forwarded, (
            f"{step['name']} must forward both webhook keyring variables"
        )
    assert containers == 3
