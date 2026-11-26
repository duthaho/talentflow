from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.workflow.domain.candidate_state_machine import CandidateStage

CATALOG = yaml.safe_load(Path("docs/events/asyncapi.yaml").read_text())
MESSAGES: dict[str, dict[str, Any]] = CATALOG["components"]["messages"]
SCHEMAS: dict[str, dict[str, Any]] = CATALOG["components"]["schemas"]
EVENT_TYPE = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*\.v[1-9][0-9]*$")
OUTBOX_TOPIC = re.compile(r'topic="([^"]+)"')


def _resolve(node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = SCHEMAS[node["$ref"].rsplit("/", 1)[-1]]
    return node


def _event_part(message: dict[str, Any]) -> dict[str, Any]:
    return message["payload"]["allOf"][1]["properties"]


def _data_schema(message: dict[str, Any]) -> dict[str, Any]:
    return _resolve(_event_part(message)["data"])


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_message_name_equals_its_type_and_channel_address(key: str) -> None:
    message = MESSAGES[key]
    name = message["name"]

    assert EVENT_TYPE.fullmatch(name)
    assert _event_part(message)["type"]["const"] == name
    assert message["payload"]["allOf"][0] == {"$ref": "#/components/schemas/Envelope"}
    addresses = [
        channel["address"]
        for channel in CATALOG["channels"].values()
        if channel["bindings"].get("$ref", "").endswith("/EventsExchange")
        and any(ref["$ref"].endswith(f"/{key}") for ref in channel["messages"].values())
    ]
    assert addresses == [name]


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_message_declares_owner_status_and_webhook_visibility(key: str) -> None:
    meta = MESSAGES[key]["x-talentflow"]

    assert meta["status"] in {"active", "planned", "reserved"}
    assert re.fullmatch(r"DUTH-\d+", meta["first_publisher"])
    assert isinstance(meta["webhook"], bool)
    assert _event_part(MESSAGES[key])["source"]["const"] == f"urn:talentflow:{meta['context']}"


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_payload_fields_cannot_carry_free_text(key: str) -> None:
    data = _data_schema(MESSAGES[key])

    for field, raw in data["properties"].items():
        schema = _resolve(raw)
        if schema["type"] == "string":
            constrained = {"enum", "const", "format", "pattern"} & schema.keys()
            assert constrained, f"{key}.{field} is an unconstrained string"
        else:
            assert schema["type"] in {"integer", "boolean"}, f"{key}.{field}"


def test_every_outbox_topic_written_by_the_code_is_in_the_catalog() -> None:
    names = {message["name"] for message in MESSAGES.values()}
    written = {
        topic
        for path in Path("app").rglob("*.py")
        for topic in OUTBOX_TOPIC.findall(path.read_text())
    }

    assert written
    assert written <= names


def test_catalog_stage_enum_matches_the_state_machine() -> None:
    assert SCHEMAS["CandidateStage"]["enum"] == [stage.value for stage in CandidateStage]


def test_active_outbox_payload_keeps_its_original_required_fields() -> None:
    data = _data_schema(MESSAGES["OfferApprovalRecordedV1"])

    assert data["required"] == ["offer_id", "decision", "actor_id"]
