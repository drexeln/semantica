"""Backup and isolated-restore helpers for the local FALCON journal."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .falcon_journal import FalconJournal, JournalError
from .falcon_lifecycle import LIFECYCLE_SCHEMA_VERSION


class RecoveryError(RuntimeError):
    """Raised when a FALCON backup cannot be verified or isolated safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(str(path))
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])
    finally:
        connection.close()


def _schema_version(path: Path) -> int:
    connection = sqlite3.connect(str(path))
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _install_without_overwrite(temporary: Path, target: Path) -> None:
    """Atomically publish a completed file, failing if the name is already used."""
    try:
        # A same-directory hard link is an atomic create-if-absent operation on
        # the local Windows/Linux filesystems supported by the journal.
        os.link(str(temporary), str(target))
    except FileExistsError as exc:
        raise RecoveryError("Destination already exists; existing data will not be overwritten") from exc
    except OSError as exc:
        raise RecoveryError("Filesystem cannot safely publish a no-overwrite recovery file") from exc
    try:
        temporary.unlink()
    except OSError:
        # Remove the just-created link if we cannot finish the move. It is safe
        # to remove because this invocation created it with exclusive semantics.
        try:
            target.unlink()
        finally:
            raise


def backup_journal(journal: FalconJournal, destination: str) -> Dict[str, Any]:
    """Create a new verified SQLite backup and manifest; never overwrite files."""
    target = Path(destination).expanduser().resolve()
    source = journal.path.resolve()
    if target == source:
        raise RecoveryError("Backup destination must differ from active journal")
    manifest_path = Path(str(target) + ".manifest.json")
    if target.exists() or manifest_path.exists():
        raise RecoveryError("Backup or manifest already exists; choose a new destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_handle, temp_name = tempfile.mkstemp(prefix=".falcon-backup-", suffix=".sqlite3", dir=str(target.parent))
    os.close(temp_handle)
    temporary = Path(temp_name)
    manifest_temp = None
    installed_backup = False
    installed_manifest = False
    try:
        source_connection = sqlite3.connect(str(source), timeout=journal.timeout_seconds)
        backup_connection = sqlite3.connect(str(temporary))
        try:
            source_connection.backup(backup_connection)
        finally:
            backup_connection.close()
            source_connection.close()
        integrity = _integrity(temporary)
        schema_version = _schema_version(temporary)
        if integrity != "ok" or schema_version != LIFECYCLE_SCHEMA_VERSION:
            raise RecoveryError("Created backup failed integrity or schema validation")
        manifest = {
            "manifest_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": schema_version,
            "file_name": target.name,
            "size_bytes": temporary.stat().st_size,
            "sha256": _sha256(temporary),
            "integrity_check": integrity,
        }
        temp_manifest_handle, temp_manifest_name = tempfile.mkstemp(
            prefix=".falcon-manifest-", suffix=".json", dir=str(target.parent)
        )
        os.close(temp_manifest_handle)
        manifest_temp = Path(temp_manifest_name)
        manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists() or manifest_path.exists():
            raise RecoveryError("Backup destination appeared during creation")
        _install_without_overwrite(temporary, target)
        installed_backup = True
        _install_without_overwrite(manifest_temp, manifest_path)
        installed_manifest = True
        return {"backup_path": str(target), "manifest_path": str(manifest_path), **manifest}
    except (OSError, sqlite3.Error, JournalError) as exc:
        if isinstance(exc, RecoveryError):
            raise
        raise RecoveryError("Could not create FALCON journal backup") from exc
    finally:
        for candidate in (temporary, manifest_temp):
            if candidate and candidate.exists():
                candidate.unlink()
        if installed_backup and not installed_manifest and target.exists():
            target.unlink()


def restore_isolated(
    backup_path: str,
    destination: str,
    manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify a backup and restore it to a new, isolated path without overwrite."""
    source = Path(backup_path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve() if manifest_path else Path(str(source) + ".manifest.json")
    if not source.is_file() or not manifest_file.is_file():
        raise RecoveryError("Backup and sidecar manifest are both required")
    if target == source or target == manifest_file:
        raise RecoveryError("Restore destination must be separate from backup and manifest")
    if target.exists():
        raise RecoveryError("Restore destination already exists; active data will not be overwritten")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("Backup manifest is unreadable") from exc
    if manifest.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
        raise RecoveryError("Backup schema version is not supported")
    if manifest.get("size_bytes") != source.stat().st_size or manifest.get("sha256") != _sha256(source):
        raise RecoveryError("Backup does not match its manifest hash/size")
    if _integrity(source) != "ok":
        raise RecoveryError("Backup failed SQLite integrity_check")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_handle, temp_name = tempfile.mkstemp(prefix=".falcon-restore-", suffix=".sqlite3", dir=str(target.parent))
    os.close(temp_handle)
    temporary = Path(temp_name)
    try:
        source_connection = sqlite3.connect(str(source))
        target_connection = sqlite3.connect(str(temporary))
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        if _integrity(temporary) != "ok" or _schema_version(temporary) != LIFECYCLE_SCHEMA_VERSION:
            raise RecoveryError("Restored copy failed validation")
        if target.exists():
            raise RecoveryError("Restore destination appeared during restore")
        _install_without_overwrite(temporary, target)
        restored = FalconJournal(str(target))
        return {
            "restore_path": str(target),
            "schema_version": restored.schema_version(),
            "record_count": len(restored.list_latest(limit=1000)),
            "integrity_check": restored.integrity_check(),
            "backup_sha256": manifest["sha256"],
        }
    except (OSError, sqlite3.Error, JournalError) as exc:
        if isinstance(exc, RecoveryError):
            raise
        raise RecoveryError("Could not restore FALCON journal") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
