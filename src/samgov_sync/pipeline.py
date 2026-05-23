"""Orchestrates the full SAM.gov → enrich → write pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from .config import OllamaConfig, SearchProfile
from .ollama_client import summarize as ollama_summarize
from .posters.base import Writer, SyncStats, fingerprint
from .sam_client import search as sam_search

_FIELD_MAP = {
    "Title":              "title",
    "NoticeId":           "noticeId",
    "SolicitationNumber": "solicitationNumber",
    "Department":         "fullParentPathName",
    "OfficeAddress":      "officeAddress",
    "PostedDate":         "postedDate",
    "ResponseDeadline":   "responseDeadLine",
    "SetAside":           "typeOfSetAsideDescription",
    "NaicsCode":          "naicsCode",
    "OpportunityType":    "type",
    "Active":             "active",
    "Description":        "description",
}

_TITLE_MAX = 255
_SAM_OPP_URL = "https://sam.gov/opp/{}/view"
_OPPS_DIR = Path("state/opps")


class Pipeline:
    def __init__(
        self,
        ollama_cfg: Optional[OllamaConfig],
        writers: list[Writer],
        progress: Callable[[str], None] = print,
    ):
        self._ollama_cfg = ollama_cfg
        self._writers = writers
        self._progress = progress

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_profiles(self, profile_writers: list[tuple[SearchProfile, list[Writer]]]) -> SyncStats:
        self._load_writers()
        for profile, writers in profile_writers:
            self._progress("")
            self._sync_profile(profile, writers)
        self._flush_writers()
        return self._aggregate_stats()

    def run(self, profiles: list[SearchProfile]) -> SyncStats:
        return self.run_profiles([(p, self._writers) for p in profiles])

    # ------------------------------------------------------------------
    # Writer lifecycle
    # ------------------------------------------------------------------

    def _load_writers(self) -> None:
        for writer in self._writers:
            writer.load()

    def _flush_writers(self) -> None:
        for writer in self._writers:
            writer.flush()

    def _aggregate_stats(self) -> SyncStats:
        totals = SyncStats()
        for writer in self._writers:
            totals += writer.stats
        return totals

    # ------------------------------------------------------------------
    # Profile sync
    # ------------------------------------------------------------------

    def _sync_profile(self, profile: SearchProfile, writers: list[Writer]) -> None:
        seen = self._search_and_dispatch(profile, writers)
        self._monitor_and_dispatch(seen, writers)

    def _search_and_dispatch(self, profile: SearchProfile, writers: list[Writer]) -> set[str]:
        self._progress(f"[{profile.name}] Searching SAM.gov...")
        seen: set[str] = set()
        posted_from, posted_to = profile.date_range()
        for raw in sam_search(profile.url, posted_from, posted_to, progress=self._progress):
            notice_id = raw.get("noticeId")
            if not notice_id or notice_id in seen:
                continue
            seen.add(notice_id)
            self._dispatch(self._enrich(raw), writers)
        return seen

    def _monitor_and_dispatch(self, seen: set[str], writers: list[Writer]) -> None:
        tracked: set[str] = set()
        for writer in writers:
            tracked |= writer.active_ids()
        to_check = tracked - seen
        if not to_check:
            return
        self._progress(f"  Closing {len(to_check)} item(s) no longer in search results...")
        for notice_id in to_check:
            fields = _load_cached_opp(notice_id)
            if not fields:
                continue
            fields["Active"] = "No"
            self._dispatch(fields, writers)

    def _dispatch(self, fields: dict[str, Any], writers: list[Writer]) -> None:
        notice_id = fields.get("NoticeId", "")
        results = [(w, *w.handle(fields)) for w in writers]
        actions = [action for _, action, _ in results]

        errors = [(w, detail) for w, action, detail in results if action == "error"]
        for w, detail in errors:
            self._progress(f"  [!] {notice_id}: {w.name} failed — {detail}")

        if "created" in actions:
            self._progress(f"  [+] {notice_id}: {fields.get('Title', '')[:70]}")
            for writer, action, detail in results:
                if action in ("created", "updated"):
                    self._progress(f"      {writer.name:<12} ok")
        elif "updated" in actions:
            self._progress(f"  [~] {notice_id}: updated")

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _enrich(self, raw: dict[str, Any], summarize: bool = True) -> dict[str, Any]:
        fields = _to_fields(raw)
        cached = _load_cached_opp(fields.get("NoticeId", ""))
        if summarize:
            self._apply_summary(fields, cached)
        return fields

    def _apply_summary(self, fields: dict[str, Any], cached: Optional[dict[str, Any]]) -> None:
        notice_id = fields.get("NoticeId", "")
        if cached and "Summary" in cached:
            fields["Summary"] = cached["Summary"]
            fields["Deliverables"] = cached.get("Deliverables", [])
        elif self._ollama_cfg:
            self._progress(f"  [ai] {notice_id}: summarizing…")
            result = ollama_summarize(self._ollama_cfg.host, self._ollama_cfg.model, fields)
            if result:
                fields["Summary"] = result.get("summary", "")
                fields["Deliverables"] = result.get("deliverables", [])
                self._progress(f"  [ai] {notice_id}: done")


# ------------------------------------------------------------------
# Field mapping
# ------------------------------------------------------------------

def _to_fields(opp: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for dest_key, src_key in _FIELD_MAP.items():
        val = opp.get(src_key) or ""
        if dest_key == "Title":
            val = str(val)[:_TITLE_MAX]
        fields[dest_key] = str(val) if not isinstance(val, str) else val
    notice_id = opp.get("noticeId", "")
    fields["UiLink"] = opp.get("uiLink") or (_SAM_OPP_URL.format(notice_id) if notice_id else "")
    return fields


def _load_cached_opp(notice_id: str) -> Optional[dict[str, Any]]:
    path = _OPPS_DIR / f"{notice_id}.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None
