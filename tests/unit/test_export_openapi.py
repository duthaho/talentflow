import json

from scripts.export_openapi import render


def test_render_is_deterministic_and_contains_candidate_and_requisition_routes():
    first = render()

    assert first == render()
    assert first.endswith("\n")
    paths = json.loads(first)["paths"]
    assert "/v1/candidate-cases" in paths
    assert "/v1/requisitions" in paths
