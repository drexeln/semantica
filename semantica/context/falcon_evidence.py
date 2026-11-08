"""Source and evidence adapters for the local FALCON lifecycle."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from .falcon_lifecycle import EPISTEMIC_STATES, SourceReference, TemporalValue, model_payload


def temporal_value(value: Any, timezone_name: Optional[str] = None, precision: Optional[str] = None):
    """Preserve supplied time and metadata; never infer missing clock details."""
    if value is None or value == "":
        return None
    if isinstance(value, TemporalValue):
        return model_payload(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must include a timezone or remain unknown")
        timezone_name = timezone_name or value.tzname()
        precision = precision or ("microsecond" if value.microsecond else "second")
        value = value.isoformat()
    if isinstance(value, Mapping):
        raw_value = value.get("value")
        if raw_value is None:
            return None
        return model_payload(
            TemporalValue(
                value=str(raw_value),
                timezone=value.get("timezone"),
                precision=value.get("precision"),
            )
        )
    return model_payload(
        TemporalValue(value=str(value), timezone=timezone_name, precision=precision)
    )


def source_reference_payload(
    *,
    source_system: str,
    source_id: str,
    object_type: str,
    granularity: str,
    content: Optional[str] = None,
    source_revision: Optional[str] = None,
    content_hash: Optional[str] = None,
    locator: Optional[str] = None,
    tenant_or_partition: Optional[str] = None,
    event_time: Any = None,
    captured_at: Any = None,
    processed_at: Any = None,
    time_zone: Optional[str] = None,
    time_precision: Optional[str] = None,
    access_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a versioned source reference without importing domain master data."""
    required = {
        "source_system": source_system,
        "source_id": source_id,
        "object_type": object_type,
        "granularity": granularity,
    }
    missing = [key for key, value in required.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise ValueError("Missing source reference fields: " + ", ".join(missing))
    digest = content_hash
    if digest is None and content is not None:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    reference = SourceReference(
        source_system=source_system.strip(),
        source_id=source_id.strip(),
        object_type=object_type.strip(),
        granularity=granularity.strip(),
        source_revision=source_revision,
        content_hash=digest,
        locator=locator,
        tenant_or_partition=tenant_or_partition,
        event_time=temporal_value(event_time, time_zone, time_precision),
        captured_at=temporal_value(captured_at, time_zone, time_precision),
        processed_at=temporal_value(processed_at, time_zone, time_precision),
        access_class=access_class,
    )
    return model_payload(reference)


def evidence_record_payload(
    *,
    evidence_id: str,
    source_reference: Mapping[str, Any],
    content: str,
    epistemic_state: str = "reported",
    scope: Optional[str] = None,
    verification_state: str = "unverified",
    assertion: Optional[str] = None,
) -> Dict[str, Any]:
    """Map locally supplied evidence to the existing canonical EvidenceRecord."""
    if not evidence_id or not content:
        raise ValueError("Evidence ID and original content are required")
    if epistemic_state not in EPISTEMIC_STATES:
        raise ValueError("Unsupported evidence epistemic_state")
    if verification_state not in {"unverified", "self_reported", "independently_evidenced"}:
        raise ValueError("Unsupported evidence verification_state")
    if not source_reference.get("source_id"):
        raise ValueError("Evidence requires a stable source ID")
    return {
        "evidence_id": evidence_id,
        "source_reference": dict(source_reference),
        "content": content,
        "assertion": assertion,
        "scope": scope,
        "epistemic_state": epistemic_state,
        "verification_state": verification_state,
    }
