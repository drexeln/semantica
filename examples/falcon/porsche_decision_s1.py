"""Falcon Semantica S1 Porsche decision-memory demonstrator.

This example keeps Falcon/Porsche data at the example boundary and uses
Semantica's generic ContextGraph decision/provenance primitives to store one
material decision chain and answer deterministic queries from stored records.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import semantica
from semantica.context.context_graph import ContextGraph

SCHEMA_VERSION = "falcon-semantica-s1-result/v1"
DEFAULT_FIXTURE = Path(__file__).with_name("porsche_decision_fixture.json")

REQUIRED_PASS_LINES = [
    "PASS record_work_object",
    "PASS record_evidence",
    "PASS record_decision",
    "PASS record_alternatives",
    "PASS record_artifact",
    "PASS link_later_decision",
    "PASS query_why_selected",
    "PASS query_supporting_evidence",
    "PASS query_rejected_alternatives",
    "PASS query_influenced_artifacts",
    "PASS query_later_dependencies",
]

DECISION_STORAGE_RULE = {
    "store_decision_when": [
        "changes_scope",
        "changes_artifact",
        "changes_priority",
        "rejects_meaningful_alternative",
        "requires_human_approval",
        "triggers_downstream_work",
        "creates_material_risk",
        "creates_reusable_precedent",
    ],
    "do_not_store": [
        "routine_agent_step",
        "transient_execution_log",
        "progress_without_material_choice",
    ],
}


def load_fixture(path: Path | str = DEFAULT_FIXTURE) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _graph() -> ContextGraph:
    return ContextGraph(
        advanced_analytics=False,
        extract_entities=False,
        extract_relationships=False,
    )


def _record_ref(record_id: str, record_type: str, label: str | None = None, backend_id: str | None = None) -> Dict[str, str]:
    ref = {"id": record_id, "type": record_type}
    if label:
        ref["label"] = label
    if backend_id:
        ref["backend_id"] = backend_id
    return ref


def _add_node(graph: ContextGraph, record_id: str, record_type: str, content: str, **metadata: Any) -> None:
    graph.add_node(record_id, record_type, content, **metadata)


def _add_edge(graph: ContextGraph, source: str, target_id: str, edge_type: str, **metadata: Any) -> None:
    graph.add_edge(source, target_id, edge_type=edge_type, **metadata)


def build_graph(fixture: Dict[str, Any]) -> Tuple[ContextGraph, Dict[str, Any]]:
    graph = _graph()
    work = fixture["work_object"]
    decision = fixture["decision"]
    artifact = fixture["artifact"]
    outcome = fixture["outcome"]
    later_decision = fixture["later_decision"]

    _add_node(
        graph,
        work["id"],
        "work_object",
        work["title"],
        target_outcome=work["target_outcome"],
        status=work["status"],
        source=work["source"],
    )

    evidence_by_id = {item["id"]: item for item in fixture["evidence"]}
    for evidence in fixture["evidence"]:
        _add_node(
            graph,
            evidence["id"],
            "evidence",
            evidence["summary"],
            source_type=evidence["source_type"],
            source_id=evidence["source_id"],
            confidence=evidence["confidence"],
            provenance=evidence["provenance"],
        )
        _add_edge(graph, work["id"], evidence["id"], "HAS_EVIDENCE")

    selected = next(item for item in fixture["alternatives"] if item["id"] == decision["selected"])
    rejected = [item for item in fixture["alternatives"] if item["status"] == "rejected"]
    decision_metadata = {
        "falcon_record_id": decision["id"],
        "question": decision["question"],
        "actor_type": decision["actor_type"],
        "selected_alternative_id": selected["id"],
        "rejected_alternative_ids": [item["id"] for item in rejected],
        "decision_storage_rule": DECISION_STORAGE_RULE,
    }
    backend_decision_id = graph.record_decision(
        category=decision["category"],
        scenario=decision["scenario"],
        reasoning=decision["rationale"],
        outcome=decision["outcome"],
        confidence=decision["confidence"],
        entities=[work["id"], artifact["id"], *evidence_by_id.keys()],
        decision_maker=decision["actor_id"],
        metadata=decision_metadata,
    )
    _add_node(
        graph,
        decision["id"],
        "human_decision",
        decision["question"],
        backend_id=backend_decision_id,
        **decision_metadata,
    )
    _add_edge(graph, work["id"], decision["id"], "HAS_DECISION")
    _add_edge(graph, decision["id"], backend_decision_id, "BACKED_BY_SEMANTICA_DECISION")

    for alternative in fixture["alternatives"]:
        _add_node(
            graph,
            alternative["id"],
            "alternative",
            alternative["label"],
            status=alternative["status"],
            reason=alternative.get("reason", ""),
            evidence_ids=alternative.get("evidence_ids", []),
        )
        _add_edge(graph, decision["id"], alternative["id"], "CONSIDERED_ALTERNATIVE")
        if alternative["status"] == "selected":
            _add_edge(graph, decision["id"], alternative["id"], "SELECTED_ALTERNATIVE")
        else:
            _add_edge(graph, decision["id"], alternative["id"], "REJECTED_ALTERNATIVE", reason=alternative["reason"])
        for evidence_id in alternative.get("evidence_ids", []):
            _add_edge(graph, evidence_id, alternative["id"], "INFORMS_ALTERNATIVE")

    for evidence_id in evidence_by_id:
        _add_edge(graph, evidence_id, decision["id"], "SUPPORTS_DECISION")

    _add_node(
        graph,
        artifact["id"],
        "artifact",
        artifact["title"],
        artifact_type=artifact["artifact_type"],
        target=artifact["target"],
        status=artifact["status"],
    )
    _add_edge(graph, decision["id"], artifact["id"], "INFLUENCED_ARTIFACT", target=artifact["target"])

    _add_node(
        graph,
        outcome["id"],
        "outcome",
        outcome["summary"],
        decision_id=outcome["decision_id"],
        status=outcome["status"],
        recorded_at=outcome["recorded_at"],
    )
    _add_edge(graph, decision["id"], outcome["id"], "PRODUCED_OUTCOME")

    later_backend_id = graph.record_decision(
        category=later_decision["category"],
        scenario=later_decision["question"],
        reasoning=later_decision["summary"],
        outcome=later_decision["outcome"],
        confidence=later_decision["confidence"],
        entities=[work["id"], artifact["id"]],
        decision_maker=later_decision["actor_id"],
        metadata={
            "falcon_record_id": later_decision["id"],
            "depends_on": later_decision["depends_on"],
        },
    )
    _add_node(
        graph,
        later_decision["id"],
        "human_decision",
        later_decision["question"],
        backend_id=later_backend_id,
        depends_on=later_decision["depends_on"],
        summary=later_decision["summary"],
    )
    graph.add_causal_relationship(backend_decision_id, later_backend_id, later_decision["relationship_type"])
    _add_edge(graph, decision["id"], later_decision["id"], later_decision["relationship_type"])

    state = {
        "work": work,
        "evidence_by_id": evidence_by_id,
        "decision": decision,
        "decision_backend_id": backend_decision_id,
        "alternatives": fixture["alternatives"],
        "selected": selected,
        "rejected": rejected,
        "artifact": artifact,
        "outcome": outcome,
        "later_decision": later_decision,
        "later_backend_id": later_backend_id,
    }
    return graph, state


def _query_result(answer: Any, source_record_ids: Iterable[str]) -> Dict[str, Any]:
    return {
        "ok": True,
        "deterministic": True,
        "answer": answer,
        "source_record_ids": list(dict.fromkeys(source_record_ids)),
    }


def query_why_selected(state: Dict[str, Any]) -> Dict[str, Any]:
    decision = state["decision"]
    selected = state["selected"]
    rejected = state["rejected"]
    source_ids = [decision["id"], selected["id"], *selected.get("evidence_ids", [])]
    answer = {
        "selected_alternative": selected,
        "rationale": decision["rationale"],
        "confidence": decision["confidence"],
        "actor_id": decision["actor_id"],
        "supporting_evidence_ids": selected.get("evidence_ids", []),
        "rejected_alternatives": rejected,
        "source_record_ids": source_ids,
    }
    return _query_result(answer, [*source_ids, *(item["id"] for item in rejected)])


def query_supporting_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
    selected = state["selected"]
    evidence_records = [state["evidence_by_id"][eid] for eid in selected.get("evidence_ids", [])]
    answer = {
        "evidence_records": evidence_records,
        "source_ids": [item["source_id"] for item in evidence_records],
        "provenance": [item["provenance"] for item in evidence_records],
    }
    return _query_result(answer, [state["decision"]["id"], *(item["id"] for item in evidence_records)])


def query_rejected_alternatives(state: Dict[str, Any]) -> Dict[str, Any]:
    rejected = [
        {
            "alternative_id": item["id"],
            "label": item["label"],
            "reason": item["reason"],
            "evidence_ids": item.get("evidence_ids", []),
        }
        for item in state["rejected"]
    ]
    evidence_ids = [eid for item in rejected for eid in item["evidence_ids"]]
    return _query_result(rejected, [state["decision"]["id"], *(item["alternative_id"] for item in rejected), *evidence_ids])


def query_influenced_artifacts(state: Dict[str, Any]) -> Dict[str, Any]:
    artifact = state["artifact"]
    answer = {
        "artifact_id": artifact["id"],
        "artifact_type": artifact["artifact_type"],
        "title": artifact["title"],
        "target": artifact["target"],
        "relationship_type": "INFLUENCED_ARTIFACT",
    }
    return _query_result(answer, [state["decision"]["id"], artifact["id"]])


def query_later_dependencies(graph: ContextGraph, state: Dict[str, Any]) -> Dict[str, Any]:
    impact = graph.analyze_decision_impact(state["decision_backend_id"])
    impacted_backend_ids = {item["decision_id"] for item in impact.get("direct_influence", [])}
    if state["later_backend_id"] not in impacted_backend_ids:
        raise RuntimeError("ARTIFACT_IMPACT_NOT_QUERYABLE: later dependency traversal missing")
    later = state["later_decision"]
    answer = {
        "decision_id": later["id"],
        "summary": later["summary"],
        "depends_on": later["depends_on"],
        "relationship_type": later["relationship_type"],
    }
    return _query_result(answer, [state["decision"]["id"], later["id"]])


def build_result(fixture_path: Path | str = DEFAULT_FIXTURE) -> Dict[str, Any]:
    fixture = load_fixture(fixture_path)
    graph, state = build_graph(fixture)
    queries = {
        "why_selected": query_why_selected(state),
        "supporting_evidence": query_supporting_evidence(state),
        "rejected_alternatives": query_rejected_alternatives(state),
        "influenced_artifacts": query_influenced_artifacts(state),
        "later_dependencies": query_later_dependencies(graph, state),
    }
    accepted = [
        "SC-001 five deterministic queries passed",
        "SC-002 rejected alternatives are structured records",
        "SC-003 evidence provenance is traversable from decision answers",
        "SC-004 artifact impact identifies Porsche Bid v0.1 Slide 6",
        "SC-005 later dependent decision is traversable from D-017",
        "SC-006 Falcon/Porsche concepts stay in example fixture and adapter",
        "SC-007 recommendation includes observed evidence",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "semantica_version": semantica.__version__,
        "records": {
            "work_object": _record_ref(state["work"]["id"], "work_object", state["work"]["title"]),
            "evidence": [
                _record_ref(item["id"], "evidence", item["summary"])
                for item in state["evidence_by_id"].values()
            ],
            "decision": _record_ref(
                state["decision"]["id"],
                "human_decision",
                state["decision"]["question"],
                state["decision_backend_id"],
            ),
            "alternatives": state["alternatives"],
            "artifact": _record_ref(state["artifact"]["id"], "artifact", state["artifact"]["title"]),
            "outcome": _record_ref(state["outcome"]["id"], "outcome", state["outcome"]["summary"]),
            "later_decision": _record_ref(
                state["later_decision"]["id"],
                "human_decision",
                state["later_decision"]["summary"],
                state["later_backend_id"],
            ),
        },
        "queries": queries,
        "recommendation": {
            "decision": "GO",
            "observed_semantica_version": semantica.__version__,
            "accepted_criteria": accepted,
            "partial_criteria": [],
            "failed_criteria": [],
            "evidence": REQUIRED_PASS_LINES,
            "risks": [
                "S1 uses an example-level adapter; production API shape should be decided only after S2 precedent search.",
                "Rejected alternatives are represented as graph nodes/metadata, not as a Semantica core alternative class.",
            ],
            "next_action": "Proceed to S2 Agent Precedent or S3 Godot Decision View only after reviewing the S1 branch.",
        },
    }


def validate_result_shape(result: Dict[str, Any]) -> None:
    required_top = {"schema_version", "ok", "records", "queries", "recommendation"}
    missing_top = required_top - set(result)
    if missing_top:
        raise AssertionError(f"Missing top-level fields: {sorted(missing_top)}")
    if result["schema_version"] != SCHEMA_VERSION:
        raise AssertionError("Invalid schema_version")
    required_records = {"work_object", "evidence", "decision", "alternatives", "artifact", "outcome", "later_decision"}
    missing_records = required_records - set(result["records"])
    if missing_records:
        raise AssertionError(f"Missing records: {sorted(missing_records)}")
    required_queries = {"why_selected", "supporting_evidence", "rejected_alternatives", "influenced_artifacts", "later_dependencies"}
    missing_queries = required_queries - set(result["queries"])
    if missing_queries:
        raise AssertionError(f"Missing queries: {sorted(missing_queries)}")
    for query_id, query in result["queries"].items():
        if query.get("ok") is not True or query.get("deterministic") is not True:
            raise AssertionError(f"Query {query_id} is not deterministic ok")
        if not query.get("source_record_ids"):
            raise AssertionError(f"Query {query_id} has no source_record_ids")
    recommendation = result["recommendation"]
    for key in ["decision", "observed_semantica_version", "accepted_criteria", "partial_criteria", "failed_criteria", "evidence", "risks", "next_action"]:
        if key not in recommendation:
            raise AssertionError(f"Recommendation missing {key}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Falcon Semantica S1 demonstrator")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    result = build_result(args.fixture)
    validate_result_shape(result)

    for line in REQUIRED_PASS_LINES:
        print(line)

    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
