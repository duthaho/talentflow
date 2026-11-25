import json

from scripts.export_openapi import render


def test_render_is_deterministic_and_contains_candidate_routes():
    first = render()

    assert first == render()
    assert first.endswith("\n")
    assert "/v1/candidate-cases" in json.loads(first)["paths"]
