"""Orchestrates the full SAM.gov → enrich → write pipeline."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional

from .config import OllamaConfig, SearchProfile
from .ollama_client import summarize as ollama_summarize
from .posters.base import Writer, SyncStats, fingerprint
from .sam_client import fetch_by_id, fetch_description
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
        sam_api_key: str,
        ollama_cfg: Optional[OllamaConfig],
        writers: list[Writer],
        progress: Callable[[str], None] = print,
    ):
        self._api_key = sam_api_key
        self._ollama_cfg = ollama_cfg
        self._writers = writers
        self._progress = progress

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_profiles(self, profile_writers: list[tuple]) -> SyncStats:
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
        self._progress(f"[{profile.name}] Searching SAM.gov: queries={profile.queries}")
        seen: set[str] = set()
        for query in profile.queries:
            for raw in sam_search(self._api_key, profile.as_sam_params(query), progress=self._progress):
                if profile.active_only and raw.get("active", "").upper() != "YES":
                    continue
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
        self._progress(f"  Re-checking {len(to_check)} tracked item(s) outside search window...")
        for notice_id in to_check:
            raw = fetch_by_id(self._api_key, notice_id)
            if raw:
                self._dispatch(self._enrich(raw), writers)

    def _dispatch(self, fields: dict[str, Any], writers: list[Writer]) -> None:
        notice_id = fields.get("NoticeId", "")
        results = [(w, *w.handle(fields)) for w in writers]
        actions = [action for _, action, _ in results]

        if "created" in actions:
            self._progress(f"  [+] {notice_id}: {fields.get('Title', '')[:70]}")
        elif "updated" in actions:
            self._progress(f"  [~] {notice_id}: updated")
        else:
            return

        for writer, action, detail in results:
            if action == "error":
                self._progress(f"      {writer.name:<12} failed — {detail}")
            elif action in ("created", "updated"):
                self._progress(f"      {writer.name:<12} ok")

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _enrich(self, raw: dict[str, Any]) -> dict[str, Any]:
        fields = _to_fields(raw)
        cached = _load_cached_opp(fields.get("NoticeId", ""))
        self._apply_full_description(fields, cached)
        self._apply_summary(fields, cached)
        return fields

    def _apply_full_description(self, fields: dict[str, Any], cached: Optional[dict[str, Any]]) -> None:
        notice_id = fields.get("NoticeId", "")
        if cached and cached.get("DescriptionFull"):
            fields["Description"] = cached["Description"]
            fields["DescriptionFull"] = True
        elif self._api_key and notice_id:
            html = fetch_description(self._api_key, notice_id)
            if html:
                fields["Description"] = _clean_description(html)
                fields["DescriptionFull"] = True

    def _apply_summary(self, fields: dict[str, Any], cached: Optional[dict[str, Any]]) -> None:
        notice_id = fields.get("NoticeId", "")
        if cached and cached.get("Summary"):
            fields["Summary"] = cached.get("Summary", "")
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

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _clean_description(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    if text.startswith("http"):
        return ""
    if "<" in text:
        s = _HTMLStripper()
        s.feed(text)
        return s.get_text()
    return text


def _to_fields(opp: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for dest_key, src_key in _FIELD_MAP.items():
        val = opp.get(src_key) or ""
        if dest_key == "Title":
            val = str(val)[:_TITLE_MAX]
        elif dest_key == "Description":
            val = _clean_description(str(val) if not isinstance(val, str) else val)
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
