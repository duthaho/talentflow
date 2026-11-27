"""Freeze the approved OpenAPI contract without a runtime YAML dependency."""

import ast
import pprint
from pathlib import Path

import yaml


def main():
    source = Path("docs/webhooks/openapi.yaml")
    target = Path("app/api/webhook_contract.py")
    contract = yaml.safe_load(source.read_text())
    values = {name: contract[name] for name in ("paths", "components", "webhooks")}
    text = target.read_text()
    assignment = next(
        node
        for node in ast.parse(text).body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "CONTRACT" for name in node.targets)
    )
    lines = text.splitlines(keepends=True)
    frozen = "CONTRACT = " + pprint.pformat(values, sort_dicts=False, width=100) + "\n"
    target.write_text(
        "".join(lines[: assignment.lineno - 1]) + frozen + "".join(lines[assignment.end_lineno :])
    )


if __name__ == "__main__":
    main()
