import json

from scripts.export_openapi import render


def test_render_is_deterministic_and_contains_candidate_and_requisition_routes():
    first = render()

    assert first == render()
    assert first.endswith("\n")
    paths = json.loads(first)["paths"]
    assert "/v1/candidate-cases" in paths
    assert "/v1/requisitions" in paths


def test_publication_explicitly_advertises_idempotency_without_changing_other_routes():
    paths = json.loads(render())["paths"]
    publication = paths["/v1/requisitions/{id}/publication"]["patch"]
    assert publication["x-idempotency-key"] is True
    key = next(item for item in publication["parameters"] if item["name"] == "Idempotency-Key")
    assert key["in"] == "header" and key["required"] is False
    stage = paths["/v1/candidate-cases/{candidate_case_id}/stage"]["patch"]
    assert any(item["name"] == "Idempotency-Key" for item in stage["parameters"])
    legal_hold = paths["/v1/candidate-cases/{candidate_case_id}/legal-hold"]["put"]
    assert all(item["name"] != "Idempotency-Key" for item in legal_hold["parameters"])
