"""FALCON lifecycle DTOs mapped onto the existing canonical vocabulary.

These Python records are transport/persistence contracts, not new ontology
classes. ``CANONICAL_TYPE_BY_RECORD`` is the single boundary map used by the
local journal and the ContextGraph projection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence


LIFECYCLE_SCHEMA_VERSION = 1

EXXETA_SHARED_VIEWS = (
    "Demand",
    "Capability",
    "Commitment",
    "Execution",
    "Economics",
    "Governance",
    "Evidence & Learning",
)

CANONICAL_TYPE_BY_RECORD = {
    "decision_definition": "DecisionDefinition",
    "decision_run": "DecisionRun",
    "decision_option": "DecisionOption",
    "intervention": "Intervention",
    "outcome_observation": "OutcomeObservation",
    "evidence_record": "EvidenceRecord",
    "business_event": "BusinessEvent",
    "capture_record": "CaptureRecord",
    "context_snapshot": "ContextSnapshot",
    "execution_receipt": "ExecutionReceipt",
    "review": "Review",
    "learning_update": "LearningUpdate",
    "report_snapshot": "ReportSnapshot",
}

EPISTEMIC_STATES = {"reported", "derived", "confirmed", "disputed", "unknown"}
EXECUTION_STATES = {
    "not_started",
    "running",
    "succeeded",
    "failed",
    "unknown",
    "partial",
    "self_reported",
}
DECISION_RUN_STATES = {"draft", "ready_for_review", "decided", "review_due", "reviewed"}
AUTHORIZATION_STATES = {
    "not_required",
    "pending",
    "approved",
    "rejected",
    "revoked",
    "expired",
}
OPTION_CLASSES = {"ACT", "HOLD", "DEFER", "INVESTIGATE", "DELEGATE", "REJECT"}


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must include a timezone or remain unknown")
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def model_payload(model: Any) -> Dict[str, Any]:
    """Return a JSON-safe payload while preserving explicit time metadata."""
    if is_dataclass(model):
        value = _json_value(asdict(model))
    elif isinstance(model, Mapping):
        value = _json_value(model)
    else:
        raise TypeError("FALCON lifecycle payloads must be dataclasses or mappings")
    if not isinstance(value, dict):
        raise TypeError("FALCON lifecycle payload must be an object")
    return value


@dataclass(frozen=True)
class TemporalValue:
    value: str
    timezone: Optional[str] = None
    precision: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("TemporalValue.value cannot be empty")


@dataclass(frozen=True)
class SourceReference:
    source_system: str
    source_id: str
    object_type: str
    granularity: str
    source_revision: Optional[str] = None
    content_hash: Optional[str] = None
    locator: Optional[str] = None
    tenant_or_partition: Optional[str] = None
    event_time: Optional[TemporalValue] = None
    captured_at: Optional[TemporalValue] = None
    processed_at: Optional[TemporalValue] = None
    access_class: Optional[str] = None


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    source_reference: SourceReference
    content: str
    epistemic_state: str = "reported"
    scope: Optional[str] = None
    verification_state: str = "unverified"

    def __post_init__(self) -> None:
        if self.epistemic_state not in EPISTEMIC_STATES:
            raise ValueError("Unsupported evidence epistemic_state")


@dataclass(frozen=True)
class DecisionDefinition:
    decision_id: str
    name: str
    objective: str
    owner_role: str
    trigger: str
    feasible_option_classes: Sequence[str]
    constraints: Sequence[str]
    evaluation_criteria: Sequence[str]
    review_policy: str
    definition_version: str

    def __post_init__(self) -> None:
        if not all((self.decision_id, self.name, self.objective, self.owner_role, self.definition_version)):
            raise ValueError("DecisionDefinition requires ID, name, objective, owner and version")
        if not self.feasible_option_classes:
            raise ValueError("DecisionDefinition requires at least one feasible option class")
        invalid = set(self.feasible_option_classes) - OPTION_CLASSES
        if invalid:
            raise ValueError("Unsupported option classes: " + ", ".join(sorted(invalid)))


@dataclass(frozen=True)
class DecisionOption:
    option_id: str
    option_class: str
    description: str
    feasibility: str = "unknown"
    effects: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    resource_estimates: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    risk_estimates: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    evidence_refs: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.option_id or not self.description:
            raise ValueError("DecisionOption requires option_id and description")
        if self.option_class not in OPTION_CLASSES:
            raise ValueError("Unsupported DecisionOption class")


@dataclass(frozen=True)
class DecisionRun:
    run_id: str
    definition_id: str
    definition_version: str
    context_snapshot_id: str
    context_hash: str
    owner_role: str
    expected_outcome: str
    options: Sequence[DecisionOption]
    state: str = "draft"
    selected_option_id: Optional[str] = None
    rationale: Optional[str] = None
    authorization_state: str = "not_required"
    evidence_refs: Sequence[str] = field(default_factory=tuple)
    assumptions: Sequence[str] = field(default_factory=tuple)
    unknowns: Sequence[str] = field(default_factory=tuple)
    scenario_rule_version: Optional[str] = None

    def __post_init__(self) -> None:
        if not all((
            self.run_id,
            self.definition_id,
            self.definition_version,
            self.context_snapshot_id,
            self.context_hash,
            self.owner_role,
            self.expected_outcome,
        )):
            raise ValueError("DecisionRun requires IDs, context, owner and expected outcome")
        if not self.options:
            raise ValueError("DecisionRun requires at least one considered option")
        ids = [option.option_id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("DecisionRun option IDs must be unique")
        if self.selected_option_id and self.selected_option_id not in ids:
            raise ValueError("Selected option must be one of the considered options")
        if self.authorization_state not in AUTHORIZATION_STATES:
            raise ValueError("Unsupported authorization state")


@dataclass(frozen=True)
class Intervention:
    intervention_id: str
    decision_run_id: str
    option_id: str
    description: str
    state: str = "locally_recorded"
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    target_id: Optional[str] = None
    target_revision: Optional[str] = None
    scope: Optional[str] = None
    expires_at: Optional[TemporalValue] = None
    revoked_at: Optional[TemporalValue] = None


@dataclass(frozen=True)
class OutcomeObservation:
    observation_id: str
    decision_run_id: str
    observation: str
    source_refs: Sequence[str]
    observed_at: Optional[TemporalValue] = None
    recorded_at: Optional[TemporalValue] = None
    verification_state: str = "self_reported"
    uncertainty: Optional[str] = None

    def __post_init__(self) -> None:
        if self.verification_state not in {"self_reported", "independently_evidenced", "unverified"}:
            raise ValueError("Unsupported observation verification_state")


@dataclass(frozen=True)
class BusinessEvent:
    event_id: str
    event_type: str
    subject_id: str
    source_ref: str
    deduplication_key: str
    rule_version: str
    occurred_at: Optional[TemporalValue] = None
    recorded_at: Optional[TemporalValue] = None
    processed_at: Optional[TemporalValue] = None
    supersedes_event_id: Optional[str] = None


def canonical_type_for(record_kind: str) -> str:
    try:
        return CANONICAL_TYPE_BY_RECORD[record_kind]
    except KeyError as exc:
        raise ValueError("Unknown FALCON lifecycle record kind: " + record_kind) from exc


def validate_payload(record_kind: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate envelope-level requirements without creating ontology classes."""
    canonical_type_for(record_kind)
    data = model_payload(payload)
    if data.get("subtype") in {"spec_authoring_v1", "spec_authoring_v2"}:
        from .falcon_spec_orders import validate_spec_payload
        validate_spec_payload(record_kind, data)
    if data.get("subtype") in {"repository_source_v1", "source_assertion_v1", "grounded_scope_v1", "grounded_context_v1", "source_change_v1", "grounded_conflict_v1"}:
        from .falcon_grounded_context import validate_grounded_payload
        validate_grounded_payload(record_kind, data)
    required = {
        "decision_definition": (
            "decision_id", "name", "objective", "owner_role", "trigger",
            "feasible_option_classes", "evaluation_criteria", "review_policy", "definition_version",
        ),
        "decision_run": (
            "run_id", "definition_id", "definition_version", "context_snapshot_id",
            "context_hash", "owner_role", "expected_outcome", "options",
        ),
        "decision_option": ("option_id", "option_class", "description"),
        "intervention": ("intervention_id", "decision_run_id", "option_id", "description"),
        "outcome_observation": ("observation_id", "decision_run_id", "observation"),
        "evidence_record": ("evidence_id", "source_reference", "content"),
        "business_event": (
            "event_id", "event_type", "activity_kind", "subject_id", "source_ref",
            "deduplication_key", "rule_version", "recorded_at",
        ),
        "capture_record": ("capture_id", "source_reference", "original_content", "original_sha256"),
        "context_snapshot": ("snapshot_id", "source_references", "content_hash", "assembly_rule_version"),
        "execution_receipt": ("receipt_id", "decision_run_id", "request_id", "status"),
        "review": ("review_id", "decision_run_id", "observation_ids", "reviewer"),
        "learning_update": (
            "learning_update_id", "review_id", "prior_version", "proposed_version",
            "proposed_change", "evidence_refs", "scope", "author",
        ),
        "report_snapshot": (
            "report_id", "decision_run_id", "purpose", "audience", "content",
            "content_sha256", "delivery_state",
        ),
    }
    for key in required.get(record_kind, ()):
        if key not in data or data[key] in (None, ""):
            raise ValueError("Missing required field for %s: %s" % (record_kind, key))
    if record_kind == "decision_run":
        options = data.get("options") or []
        if not options:
            raise ValueError("DecisionRun requires at least one considered option")
        option_ids = [option.get("option_id") for option in options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("DecisionRun option IDs must be unique")
        selected = data.get("selected_option_id")
        if selected is not None and selected not in option_ids:
            raise ValueError("Selected option must be one of the considered options")
        if data.get("authorization_state", "not_required") not in AUTHORIZATION_STATES:
            raise ValueError("Unsupported authorization state")
        if data.get("state", "draft") not in DECISION_RUN_STATES:
            raise ValueError("Unsupported DecisionRun state")
    if record_kind == "decision_option" and data.get("option_class") not in OPTION_CLASSES:
        raise ValueError("Unsupported DecisionOption class")
    if record_kind == "evidence_record" and data.get("epistemic_state", "reported") not in EPISTEMIC_STATES:
        raise ValueError("Unsupported evidence epistemic_state")
    if record_kind == "outcome_observation" and data.get("verification_state", "self_reported") not in {
        "self_reported", "independently_evidenced", "unverified"
    }:
        raise ValueError("Unsupported observation verification_state")
    return data
