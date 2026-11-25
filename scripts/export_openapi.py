"""Write the API's OpenAPI document so the web client can be generated from it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import create_app


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "web/openapi.json")
    target.write_text(render(), encoding="utf-8")
    print(f"Wrote {target}")
