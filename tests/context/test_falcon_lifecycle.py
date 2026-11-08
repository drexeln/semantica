from datetime import datetime, timezone

import pytest

from semantica.context.falcon_evidence import evidence_record_payload, source_reference_payload
from semantica.context.falcon_lifecycle import (
    CANONICAL_TYPE_BY_RECORD,
    EXXETA_SHARED_VIEWS,
    DecisionDefinition,
    DecisionOption,
    DecisionRun,
    TemporalValue,
    canonical_type_for,
    model_payload,
)


def test_lifecycle_records_map_to_existing_canonical_vocabulary():
    assert canonical_type_for("decision_run") == "DecisionRun"
    assert canonical_type_for("decision_option") == "DecisionOption"
    assert canonical_type_for("outcome_observation") == "OutcomeObservation"
    assert set(EXXETA_SHARED_VIEWS) == {
        "Demand", "Capability", "Commitment", "Execution", "Economics",
        "Governance", "Evidence & Learning",
    }
    assert "DecisionRun" in CANONICAL_TYPE_BY_RECORD.values()


def test_decision_models_require_valid_owner_options_and_selection():
    definition = DecisionDefinition(
        decision_id="decision-1",
        name="Choose a next step",
        objective="Make a useful decision",
        owner_role="Example owner",
        trigger="A decision is needed",
        feasible_option_classes=("ACT", "HOLD", "INVESTIGATE"),
        constraints=(),
        evaluation_criteria=("Evidence",),
        review_policy="Review after an observation",
        definition_version="1",
    )
    options = (
        DecisionOption("act", "ACT", "Take an action"),
        DecisionOption("hold", "HOLD", "Keep the current state"),
    )
    run = DecisionRun(
        run_id="run-1",
        definition_id=definition.decision_id,
        definition_version=definition.definition_version,
        context_snapshot_id="snapshot-1",
        context_hash="sha256:context",
        owner_role="Example owner",
        expected_outcome="A next step is selected",
        options=options,
        selected_option_id="hold",
    )
    payload = model_payload(run)
    assert payload["selected_option_id"] == "hold"
    assert payload["options"][1]["option_class"] == "HOLD"
    with pytest.raises(ValueError, match="one of the considered options"):
        DecisionRun(
            run_id="run-2", definition_id="decision-1", definition_version="1",
            context_snapshot_id="snapshot-1", context_hash="sha256:context",
            owner_role="Example owner", expected_outcome="Outcome", options=options,
            selected_option_id="missing",
        )


def test_source_reference_preserves_provided_time_precision_and_content_hash():
    source = source_reference_payload(
        source_system="local-user-input",
        source_id="capture-1",
        object_type="note",
        granularity="document",
        content="Original local input",
        source_revision="1",
        event_time={"value": "2026-10-31T12:30:00+02:00", "timezone": "Europe/Berlin", "precision": "second"},
        captured_at=TemporalValue("2026-11-01T10:00:00+00:00", "UTC", "second"),
        processed_at=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
    )
    assert source["event_time"] == {
        "value": "2026-10-31T12:30:00+02:00", "timezone": "Europe/Berlin", "precision": "second"
    }
    assert source["captured_at"]["precision"] == "second"
    assert source["processed_at"] == {
        "value": "2026-11-01T10:00:00+00:00", "timezone": "UTC", "precision": "second"
    }
    assert source["content_hash"]
    unknown_time_source = source_reference_payload(
        source_system="local-user-input", source_id="capture-2", object_type="note",
        granularity="document", content="No event time was supplied",
    )
    assert unknown_time_source["event_time"] is None


def test_manual_evidence_remains_self_reported_and_source_linked():
    source = source_reference_payload(
        source_system="local-user-input", source_id="capture-3", object_type="note",
        granularity="document", content="I completed the activity",
    )
    evidence = evidence_record_payload(
        evidence_id="evidence-3", source_reference=source,
        content="I completed the activity", verification_state="self_reported",
    )
    assert evidence["verification_state"] == "self_reported"
    assert evidence["source_reference"]["source_id"] == "capture-3"
