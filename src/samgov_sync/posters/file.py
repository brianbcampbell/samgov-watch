"""File writer — persists each opportunity as state/opps/<id>.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import Writer, fingerprint


class FileWriter(Writer):
    """Writes fully-enriched records to disk. Always registered; other writers read from these files."""

    def __init__(self, directory: Path = Path("state/opps")):
        super().__init__()
        self._dir = directory

    @property
    def name(self) -> str:
        return "File"

    def _load_existing(self) -> dict[str, tuple[str, str]]:
        result: dict[str, tuple[str, str]] = {}
        if not self._dir.exists():
            return result
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                nid = data.get("NoticeId")
                if nid:
                    result[nid] = (fingerprint(data), nid)
            except Exception:
                pass
        return result

    def _create(self, fields: dict[str, Any]) -> None:
        self._write(fields)

    def _update(self, backend_id: str, fields: dict[str, Any]) -> None:
        self._write(fields)

    def set_closed(self, notice_id: str, fields: dict[str, Any]) -> None:
        pass  # file is already current from _update

    def _write(self, fields: dict[str, Any]) -> None:
        nid = fields.get("NoticeId")
        if not nid:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{nid}.json").write_text(
            json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8"
        )
