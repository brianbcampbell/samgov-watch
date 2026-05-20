"""Abstract base class for SAM.gov result destinations."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Iterable


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


def fingerprint(fields: dict) -> str:
    return hashlib.md5(json.dumps(fields, sort_keys=True).encode()).hexdigest()


class Poster(ABC):
    """
    Interface for posting SAM.gov opportunities to a destination.

    Subclasses implement `_load_existing`, `_create`, and `_update`.
    The `sync` template method handles dedup and stats.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name shown in progress output."""

    @abstractmethod
    def _load_existing(self) -> dict[str, tuple[str, str]]:
        """
        Return a mapping of noticeId -> (fingerprint, backend_id).

        backend_id is whatever the implementation needs to update a record
        (e.g. a SharePoint item ID or a Discord message ID).
        """

    @abstractmethod
    def _create(self, fields: dict) -> None:
        """Persist a new record."""

    @abstractmethod
    def _update(self, backend_id: str, fields: dict) -> None:
        """Update an existing record identified by backend_id."""

    def active_notice_ids(self) -> set[str]:
        """
        Return notice IDs that are tracked and still marked active.

        Used by sync to re-check items that have aged out of the search window
        so status changes (e.g. opportunity closing) are still caught.
        Default: empty — subclasses that track active state should override.
        """
        return set()

    def sync(
        self,
        items: Iterable[dict],
        progress: Callable[[str], None] = print,
    ) -> SyncStats:
        """Consume *items* (already-mapped field dicts) and upsert to destination."""
        progress(f"Loading existing records from {self.name}...")
        existing = self._load_existing()

        stats = SyncStats()
        for fields in items:
            notice_id = fields.get("NoticeId", "")
            if not notice_id:
                continue
            fp = fingerprint(fields)
            try:
                if notice_id not in existing:
                    self._create(fields)
                    stats.created += 1
                    progress(f"  [+] {notice_id}: {fields.get('Title', '')[:70]}")
                elif existing[notice_id][0] != fp:
                    self._update(existing[notice_id][1], fields)
                    stats.updated += 1
                    progress(f"  [~] {notice_id}: updated")
                else:
                    stats.skipped += 1
            except Exception as exc:
                stats.errors += 1
                progress(f"  [!] {notice_id}: {exc}")

        return stats
