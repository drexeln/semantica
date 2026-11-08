"""Transactional, append-only local journal for FALCON lifecycle records."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .falcon_lifecycle import (
    LIFECYCLE_SCHEMA_VERSION,
    canonical_type_for,
    validate_payload,
)


class JournalError(RuntimeError):
    """Base class for lifecycle journal errors."""


class RevisionConflict(JournalError):
    def __init__(self, record_type: str, record_id: str, expected: int, actual: int):
        self.record_type = record_type
        self.record_id = record_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            "%s/%s revision conflict: expected %s, found %s"
            % (record_type, record_id, expected, actual)
        )


class IdempotencyConflict(JournalError):
    """Raised when one request key is reused with different content."""


class RecordNotFound(JournalError):
    pass


def default_journal_path() -> Path:
    """Return the per-user local path without creating it."""
    configured = os.environ.get("FALCON_JOURNAL_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    else:
        root = Path.home() / ".local" / "share"
    return root / "Semantica" / "FALCON" / "journal.sqlite3"


class FalconJournal:
    """SQLite-backed revision journal with idempotent append operations.

    Journal records are immutable snapshots. Domain-owned master data is stored
    only as references in their payloads. A separate SQLite connection is used
    per operation so API worker threads do not share cursors or transactions.
    """

    def __init__(self, path: Optional[str] = None, timeout_seconds: float = 10.0):
        self.path = Path(path).expanduser().resolve() if path else default_journal_path()
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=self.timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = %d" % int(self.timeout_seconds * 1000))
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > LIFECYCLE_SCHEMA_VERSION:
                raise JournalError(
                    "Journal schema %d is newer than supported schema %d"
                    % (current, LIFECYCLE_SCHEMA_VERSION)
                )
            if current not in (0, LIFECYCLE_SCHEMA_VERSION):
                raise JournalError("No migration path from journal schema %d" % current)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS falcon_records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_kind TEXT NOT NULL,
                    canonical_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    UNIQUE(record_kind, record_id, revision)
                );
                CREATE INDEX IF NOT EXISTS falcon_records_latest
                    ON falcon_records(record_kind, record_id, revision DESC);
                CREATE INDEX IF NOT EXISTS falcon_records_kind_time
                    ON falcon_records(record_kind, created_at DESC);
                CREATE TABLE IF NOT EXISTS falcon_idempotency (
                    request_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    sequence INTEGER NOT NULL REFERENCES falcon_records(sequence),
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS falcon_records_no_update
                BEFORE UPDATE ON falcon_records
                BEGIN SELECT RAISE(ABORT, 'FALCON journal records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS falcon_records_no_delete
                BEFORE DELETE ON falcon_records
                BEGIN SELECT RAISE(ABORT, 'FALCON journal records are immutable'); END;
                """
            )
            connection.execute("PRAGMA user_version = %d" % LIFECYCLE_SCHEMA_VERSION)

    @staticmethod
    def _record_id(record_kind: str, payload: Mapping[str, Any]) -> str:
        id_field = {
            "decision_definition": "decision_id",
            "decision_run": "run_id",
            "decision_option": "option_id",
            "intervention": "intervention_id",
            "outcome_observation": "observation_id",
            "evidence_record": "evidence_id",
            "business_event": "event_id",
            "capture_record": "capture_id",
            "context_snapshot": "snapshot_id",
            "execution_receipt": "receipt_id",
            "review": "review_id",
            "learning_update": "learning_update_id",
            "report_snapshot": "report_id",
        }.get(record_kind)
        value = payload.get(id_field) if id_field else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Missing stable %s for %s" % (id_field or "record ID", record_kind))
        return value

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "sequence": row["sequence"],
            "record_kind": row["record_kind"],
            "canonical_type": row["canonical_type"],
            "record_id": row["record_id"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "schema_version": row["schema_version"],
            "payload": json.loads(row["payload_json"]),
            "payload_sha256": row["payload_sha256"],
        }

    def append(
        self,
        record_kind: str,
        payload: Mapping[str, Any],
        request_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
        idempotency_fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a record revision atomically, optionally enforcing concurrency."""
        canonical_type = canonical_type_for(record_kind)
        data = validate_payload(record_kind, payload)
        record_id = self._record_id(record_kind, data)
        payload_json = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        request_basis = idempotency_fingerprint if idempotency_fingerprint is not None else payload_json
        request_fingerprint = hashlib.sha256(
            (record_kind + "\0" + record_id + "\0" + str(expected_revision) + "\0" + request_basis).encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if request_id:
                    prior = connection.execute(
                        "SELECT request_sha256, sequence FROM falcon_idempotency WHERE request_id = ?",
                        (request_id,),
                    ).fetchone()
                    if prior:
                        if prior["request_sha256"] != request_fingerprint:
                            raise IdempotencyConflict("Idempotency key was reused with a different request")
                        row = connection.execute(
                            "SELECT * FROM falcon_records WHERE sequence = ?", (prior["sequence"],)
                        ).fetchone()
                        connection.commit()
                        return self._decode(row)

                latest = connection.execute(
                    "SELECT revision FROM falcon_records WHERE record_kind = ? AND record_id = ? "
                    "ORDER BY revision DESC LIMIT 1",
                    (record_kind, record_id),
                ).fetchone()
                actual_revision = int(latest["revision"]) if latest else 0
                if expected_revision is not None and expected_revision != actual_revision:
                    raise RevisionConflict(record_kind, record_id, expected_revision, actual_revision)

                revision = actual_revision + 1
                cursor = connection.execute(
                    "INSERT INTO falcon_records (record_kind, canonical_type, record_id, revision, created_at, "
                    "schema_version, payload_json, payload_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record_kind,
                        canonical_type,
                        record_id,
                        revision,
                        created_at,
                        LIFECYCLE_SCHEMA_VERSION,
                        payload_json,
                        payload_hash,
                    ),
                )
                sequence = int(cursor.lastrowid)
                if request_id:
                    connection.execute(
                        "INSERT INTO falcon_idempotency (request_id, request_sha256, sequence, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (request_id, request_fingerprint, sequence, created_at),
                    )
                row = connection.execute(
                    "SELECT * FROM falcon_records WHERE sequence = ?", (sequence,)
                ).fetchone()
                connection.commit()
                return self._decode(row)
            except Exception:
                connection.rollback()
                raise

    def get(self, record_kind: str, record_id: str, revision: Optional[int] = None) -> Dict[str, Any]:
        with self._connection() as connection:
            if revision is None:
                row = connection.execute(
                    "SELECT * FROM falcon_records WHERE record_kind = ? AND record_id = ? "
                    "ORDER BY revision DESC LIMIT 1",
                    (record_kind, record_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM falcon_records WHERE record_kind = ? AND record_id = ? AND revision = ?",
                    (record_kind, record_id, revision),
                ).fetchone()
        if row is None:
            raise RecordNotFound("Record not found: %s/%s" % (record_kind, record_id))
        return self._decode(row)

    def list_latest(self, record_kind: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._connection() as connection:
            if record_kind:
                rows = connection.execute(
                    "SELECT r.* FROM falcon_records r JOIN (SELECT record_kind, record_id, MAX(revision) revision "
                    "FROM falcon_records WHERE record_kind = ? GROUP BY record_kind, record_id) latest "
                    "ON r.record_kind = latest.record_kind AND r.record_id = latest.record_id "
                    "AND r.revision = latest.revision ORDER BY r.sequence DESC LIMIT ?",
                    (record_kind, safe_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT r.* FROM falcon_records r JOIN (SELECT record_kind, record_id, MAX(revision) revision "
                    "FROM falcon_records GROUP BY record_kind, record_id) latest "
                    "ON r.record_kind = latest.record_kind AND r.record_id = latest.record_id "
                    "AND r.revision = latest.revision ORDER BY r.sequence DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def list_records(self, record_kind: Optional[str] = None, limit: int = 10000) -> List[Dict[str, Any]]:
        """Return immutable revisions in append order for projection/replay."""
        safe_limit = max(1, min(int(limit), 100000))
        with self._connection() as connection:
            if record_kind:
                rows = connection.execute(
                    "SELECT * FROM falcon_records WHERE record_kind = ? ORDER BY sequence LIMIT ?",
                    (record_kind, safe_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM falcon_records ORDER BY sequence LIMIT ?", (safe_limit,)
                ).fetchall()
        return [self._decode(row) for row in rows]

    def iter_records(self, record_kind: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """Stream every immutable revision from one consistent SQLite read snapshot."""
        with self._connection() as connection:
            connection.execute("BEGIN")
            try:
                if record_kind:
                    cursor = connection.execute(
                        "SELECT * FROM falcon_records WHERE record_kind = ? ORDER BY sequence", (record_kind,)
                    )
                else:
                    cursor = connection.execute("SELECT * FROM falcon_records ORDER BY sequence")
                while True:
                    rows = cursor.fetchmany(500)
                    if not rows:
                        break
                    for row in rows:
                        yield self._decode(row)
            finally:
                connection.rollback()

    def schema_version(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def integrity_check(self) -> str:
        with self._connection() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])
