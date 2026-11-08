import sqlite3

import pytest

from semantica.context.falcon_journal import (
    FalconJournal,
    IdempotencyConflict,
    RevisionConflict,
)
from semantica.context.falcon_recovery import RecoveryError, backup_journal, restore_isolated


def _definition(name="A local decision"):
    return {
        "decision_id": "definition-1",
        "name": name,
        "objective": "Choose a useful next step",
        "owner_role": "Example owner",
        "trigger": "A decision is needed",
        "feasible_option_classes": ["ACT", "HOLD", "INVESTIGATE"],
        "constraints": [],
        "evaluation_criteria": ["Evidence quality"],
        "review_policy": "Review after a reported outcome",
        "definition_version": "1",
    }


def test_append_is_immutable_revisioned_and_idempotent(tmp_path):
    journal = FalconJournal(str(tmp_path / "journal.sqlite3"))
    first = journal.append("decision_definition", _definition(), request_id="create-1", expected_revision=0)
    retry = journal.append("decision_definition", _definition(), request_id="create-1", expected_revision=0)
    assert retry["sequence"] == first["sequence"]
    assert retry["revision"] == 1

    with pytest.raises(IdempotencyConflict):
        journal.append("decision_definition", _definition("Different content"), request_id="create-1", expected_revision=0)
    with pytest.raises(RevisionConflict):
        journal.append("decision_definition", _definition("Stale update"), request_id="stale-2", expected_revision=0)

    second = journal.append("decision_definition", _definition("Revised question"), request_id="update-2", expected_revision=1)
    assert second["revision"] == 2
    assert journal.get("decision_definition", "definition-1", revision=1)["payload"]["name"] == "A local decision"
    assert journal.get("decision_definition", "definition-1")["payload"]["name"] == "Revised question"
    assert journal.list_latest("decision_definition")[0]["revision"] == 2


def test_journal_records_cannot_be_updated_or_deleted(tmp_path):
    db_path = tmp_path / "journal.sqlite3"
    journal = FalconJournal(str(db_path))
    record = journal.append("decision_definition", _definition(), request_id="create-1", expected_revision=0)
    connection = sqlite3.connect(str(db_path))
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE falcon_records SET payload_json = '{}' WHERE sequence = ?", (record["sequence"],))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM falcon_records WHERE sequence = ?", (record["sequence"],))
    finally:
        connection.close()


def test_backup_manifest_and_isolated_restore_preserve_records(tmp_path):
    journal = FalconJournal(str(tmp_path / "active.sqlite3"))
    journal.append("decision_definition", _definition(), request_id="create-1", expected_revision=0)
    backup = tmp_path / "backup.sqlite3"
    backup_info = backup_journal(journal, str(backup))
    restored_path = tmp_path / "isolated" / "restored.sqlite3"
    result = restore_isolated(str(backup), str(restored_path))
    restored = FalconJournal(str(restored_path))
    assert result["integrity_check"] == "ok"
    assert result["record_count"] == 1
    assert restored.get("decision_definition", "definition-1")["payload"]["name"] == "A local decision"
    assert backup_info["sha256"]
    with pytest.raises(RecoveryError, match="already exists"):
        restore_isolated(str(backup), str(restored_path))


def test_restore_rejects_tampered_backup(tmp_path):
    journal = FalconJournal(str(tmp_path / "active.sqlite3"))
    journal.append("decision_definition", _definition(), request_id="create-1", expected_revision=0)
    backup = tmp_path / "backup.sqlite3"
    backup_journal(journal, str(backup))
    with backup.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(RecoveryError, match="manifest hash/size"):
        restore_isolated(str(backup), str(tmp_path / "restored.sqlite3"))
