from __future__ import annotations

from examples.falcon.porsche_decision_s1 import build_result


def test_future_decision_view_payload_has_required_records() -> None:
    records = build_result()["records"]

    assert records["work_object"]["type"] == "work_object"
    assert records["decision"]["type"] == "human_decision"
    assert records["artifact"]["type"] == "artifact"
    assert records["outcome"]["type"] == "outcome"
    assert records["later_decision"]["type"] == "human_decision"
    assert len(records["evidence"]) == 2
    assert len(records["alternatives"]) == 3
    assert {item["status"] for item in records["alternatives"]} == {"selected", "rejected"}


def test_every_query_cites_source_records() -> None:
    result = build_result()

    known_ids = {
        result["records"]["work_object"]["id"],
        result["records"]["decision"]["id"],
        result["records"]["artifact"]["id"],
        result["records"]["outcome"]["id"],
        result["records"]["later_decision"]["id"],
        *(item["id"] for item in result["records"]["evidence"]),
        *(item["id"] for item in result["records"]["alternatives"]),
    }
    for query_id, query in result["queries"].items():
        assert query["source_record_ids"], query_id
        assert set(query["source_record_ids"]).issubset(known_ids), query_id


def test_recommendation_is_criterion_by_criterion() -> None:
    recommendation = build_result()["recommendation"]

    assert recommendation["decision"] == "GO"
    assert recommendation["observed_semantica_version"] == "0.6.6"
    assert recommendation["accepted_criteria"]
    assert recommendation["partial_criteria"] == []
    assert recommendation["failed_criteria"] == []
    assert recommendation["evidence"]
    assert recommendation["risks"]
    assert recommendation["next_action"]
