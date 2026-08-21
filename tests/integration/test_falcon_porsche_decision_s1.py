from __future__ import annotations

import json
from pathlib import Path

from examples.falcon.porsche_decision_s1 import REQUIRED_PASS_LINES, build_result, main


def test_records_complete_porsche_decision_chain() -> None:
    result = build_result()

    assert result["ok"] is True
    assert result["records"]["work_object"]["id"] == "porsche_tender_001"
    assert len(result["records"]["evidence"]) == 2
    assert result["records"]["decision"]["id"] == "decision_d017"
    assert len(result["records"]["alternatives"]) == 3
    assert result["records"]["artifact"]["id"] == "artifact_porsche_bid_v01_slide_6"
    assert result["records"]["outcome"]["id"] == "outcome_d017_pending_review"
    assert result["records"]["later_decision"]["id"] == "decision_d023"
    assert result["records"]["decision"]["backend_id"]
    assert result["records"]["later_decision"]["backend_id"]


def test_five_deterministic_queries_return_required_answers() -> None:
    queries = build_result()["queries"]

    assert queries["why_selected"]["answer"]["selected_alternative"]["id"] == "alternative_b"
    assert queries["why_selected"]["answer"]["actor_id"] == "falk"
    assert queries["supporting_evidence"]["answer"]["source_ids"] == [
        "source_search_mcp_reference",
        "requirement_r17",
    ]
    assert {item["alternative_id"] for item in queries["rejected_alternatives"]["answer"]} == {
        "alternative_a",
        "alternative_c",
    }
    assert queries["influenced_artifacts"]["answer"]["target"] == "Slide 6"
    assert queries["later_dependencies"]["answer"] == {
        "decision_id": "decision_d023",
        "summary": "Reduce strength of MCP claim",
        "depends_on": "decision_d017",
        "relationship_type": "INFLUENCED",
    }
    for query in queries.values():
        assert query["ok"] is True
        assert query["deterministic"] is True
        assert query["source_record_ids"]


def test_cli_writes_schema_shaped_json_and_pass_lines(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "falcon_s1_result.json"

    assert main(["--json-out", str(out_path)]) == 0

    stdout = capsys.readouterr().out.splitlines()
    assert stdout == REQUIRED_PASS_LINES
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "falcon-semantica-s1-result/v1"
    assert payload["recommendation"]["decision"] == "GO"
    assert not payload["recommendation"]["failed_criteria"]
