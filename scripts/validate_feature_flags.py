"""Offline ADR-010 lifecycle checks. The vendored schema is from flagd.dev/schema/v0/flags.json."""

import ast
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from app.modules.feature_flags.application.flags import REGISTRY


def validate(document, registry=REGISTRY, *, today=None, sources=None):
    today = today or datetime.now(UTC).date()
    schema = json.loads(Path("flags/flagd.schema.json").read_text())
    targeting_schema = json.loads(Path("flags/targeting.schema.json").read_text())
    resources = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (targeting_schema["$id"], Resource.from_contents(targeting_schema)),
            ("./targeting.json", Resource.from_contents(targeting_schema)),
        ]
    )
    errors = list(Draft7Validator(schema, registry=resources).iter_errors(document))
    if errors:
        raise ValueError(f"{errors[0].json_path}: rule 1: invalid flagd schema")
    definitions = document["flags"]
    entries = {entry.key: entry for entry in registry}
    if definitions.keys() != entries.keys():
        raise ValueError(
            f"{sorted(definitions.keys() ^ entries.keys())}: rule 5: registry mismatch"
        )

    def require(condition, key, rule):
        if not condition:
            raise ValueError(f"{key}: rule {rule}")

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for key, flag in definitions.items():
        entry = entries[key]
        require(re.fullmatch(r"(release|ops)\.[a-z]+\.[a-z0-9]+(-[a-z0-9]+)*", key), key, 2)
        metadata = flag.get("metadata", {})
        kind = key.split(".")[0]
        require(
            metadata.get("kind") == kind
            and metadata.get("owner") in ("backend", "frontend", "platform")
            and re.fullmatch(r"DUTH-\d+", str(metadata.get("issue", "")))
            and metadata.get("contextScope") == entry.scope
            and "createdAt" in metadata,
            key,
            3,
        )
        try:
            created = date.fromisoformat(metadata["createdAt"])
            if kind == "release":
                require("expiresAt" in metadata, key, 3)
                expiry = date.fromisoformat(metadata["expiresAt"])
                require(today <= expiry and 0 <= (expiry - created).days <= 90, key, 4)
            else:
                require("expiresAt" not in metadata, key, 3)
        except (ValueError, TypeError) as error:
            if "rule" in str(error):
                raise
            raise ValueError(f"{key}: rule 4: invalid date") from error
        targeting = flag.get("targeting")
        if entry.scope == "tenant":
            require(not any(node.get("var") == "role" for node in walk(targeting)), key, 6)
        require(flag["variants"] == {"on": True, "off": False} and not entry.fallback, key, 7)
        # Python equality treats 1 as True: require actual booleans as well.
        require(all(type(value) is bool for value in flag["variants"].values()), key, 7)
        if targeting is not None:
            require(isinstance(targeting, dict) and set(targeting) == {"if"}, key, 8)
            branches = targeting["if"]
            require(isinstance(branches, list) and len(branches) == 3, key, 8)
            condition, yes, no = branches
            require(isinstance(condition, dict) and set(condition) == {"in"}, key, 8)
            match = condition["in"]
            require(
                isinstance(match, list)
                and len(match) == 2
                and match[0] == {"var": "tenant_id"}
                and isinstance(match[1], list),
                key,
                8,
            )
            try:
                require(all(str(UUID(tenant)) == tenant for tenant in match[1]), key, 8)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"{key}: rule 8: tenant UUIDs only") from error
            require(yes == ("off" if kind == "ops" else "on"), key, 8)
            if no is not None:
                require(kind == "release" and flag["defaultVariant"] == "off", key, 8)
                require(isinstance(no, dict) and set(no) == {"fractional"}, key, 8)
                buckets = no["fractional"]
                require(
                    isinstance(buckets, list)
                    and len(buckets) == 2
                    and all(isinstance(b, list) and len(b) == 2 for b in buckets),
                    key,
                    8,
                )
                require(
                    {b[0] for b in buckets} == {"on", "off"}
                    and all(type(b[1]) is int and 0 <= b[1] <= 100 for b in buckets)
                    and sum(b[1] for b in buckets) == 100,
                    key,
                    8,
                )
        if entry.retired:
            require(flag["defaultVariant"] == "on" and targeting is None, key, 9)
            retired_names = set()
            registry_path = Path("app/modules/feature_flags/application/flags.py")
            for node in ast.walk(ast.parse(registry_path.read_text())):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and node.value.args
                    and isinstance(node.value.args[0], ast.Constant)
                    and node.value.args[0].value == key
                ):
                    retired_names.update(
                        target.id for target in node.targets if isinstance(target, ast.Name)
                    )
            for source in sources if sources is not None else Path("app").rglob("*.py"):
                if source == registry_path:
                    continue
                for node in ast.walk(ast.parse(source.read_text())):
                    require(
                        not (
                            (isinstance(node, ast.Constant) and node.value == key)
                            or (isinstance(node, ast.Name) and node.id in retired_names)
                            or (isinstance(node, ast.Attribute) and node.attr in retired_names)
                            or (isinstance(node, ast.alias) and node.name in retired_names)
                        ),
                        key,
                        9,
                    )


if __name__ == "__main__":
    validate(json.loads(Path("flags/talentflow.flagd.json").read_text()))
