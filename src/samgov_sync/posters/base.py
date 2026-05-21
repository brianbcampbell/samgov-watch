"""Abstract base class for SAM.gov result destinations."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_OPPS_DIR = Path("state/opps")


def save_opp(fields: dict[str, Any]) -> None:
    notice_id = fields.get("NoticeId")
    if not notice_id:
        return
    _OPPS_DIR.mkdir(parents=True, exist_ok=True)
    (_OPPS_DIR / f"{notice_id}.json").write_text(
        json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_opp(notice_id: str) -> Optional[dict[str, Any]]:
    path = _OPPS_DIR / f"{notice_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0

    def __iadd__(self, other: "SyncStats") -> "SyncStats":
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.errors += other.errors
        return self


def fingerprint(fields: dict[str, Any]) -> str:
    return hashlib.md5(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def is_closed(fields: dict[str, Any]) -> bool:
    """True when the opportunity is closed: active flag is not yes, OR response deadline is past."""
    if fields.get("Active", "Yes").upper() not in ("YES", "TRUE", "1"):
        return True
    deadline = (fields.get("ResponseDeadline") or "").strip()
    if deadline:
        dt = _parse_deadline(deadline)
        if dt is not None and dt < datetime.now(timezone.utc):
            return True
    return False


def _parse_deadline(value: str) -> Optional[datetime]:
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(value[:10], "%m/%d/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


class Writer(ABC):
    """
    Interface for writing SAM.gov opportunities to a destination.

    The pipeline calls:
      1. load()        — once before any items arrive
      2. handle(fields) — once per fully-enriched item
      3. flush()       — once after all items have been dispatched

    Writers own their internal queues. The pipeline never knows about them.
    """

    def __init__(self) -> None:
        self._existing: dict[str, tuple[str, str]] = {}
        self.stats = SyncStats()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def _load_existing(self) -> dict[str, tuple[str, str]]:
        """Return noticeId -> (fingerprint, backend_id) for all known records."""

    @abstractmethod
    def _create(self, fields: dict[str, Any]) -> None:
        """Write a new record. May enqueue and return immediately."""

    @abstractmethod
    def _update(self, backend_id: str, fields: dict[str, Any]) -> None:
        """Update an existing record. May enqueue and return immediately."""

    @abstractmethod
    def set_closed(self, notice_id: str, fields: dict[str, Any]) -> None:
        """All destination-specific actions when an opportunity closes."""

    def load(self) -> None:
        """Load existing records from the destination. Called once by the pipeline."""
        print(f"  Loading existing records from {self.name}...")
        self._existing = self._load_existing()

    def handle(self, fields: dict[str, Any]) -> tuple[str, str]:
        """Upsert one item. Returns (action, detail) where action is created/updated/skipped/error."""
        notice_id = fields.get("NoticeId", "")
        if not notice_id:
            return "skipped", ""
        fp = fingerprint(fields)
        try:
            if notice_id not in self._existing:
                self._create(fields)
                self._existing[notice_id] = (fp, notice_id)
                self.stats.created += 1
                return "created", ""
            elif self._existing[notice_id][0] != fp:
                self._update(self._existing[notice_id][1], fields)
                self._existing[notice_id] = (fp, self._existing[notice_id][1])
                self.stats.updated += 1
                return "updated", ""
            else:
                self.stats.skipped += 1
                return "skipped", ""
        except Exception as exc:
            self.stats.errors += 1
            return "error", str(exc)

    def flush(self) -> None:
        """Block until all queued writes complete. No-op for synchronous writers."""

    def active_ids(self) -> set[str]:
        """Notice IDs this writer currently tracks as active (for monitor phase)."""
        return set()
