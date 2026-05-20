"""Orchestrates SAM.gov search → field mapping → Poster.sync()."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from itertools import chain
from typing import Callable

from .config import SearchProfile
from .posters.base import Poster, SyncStats
from .sam_client import fetch_by_id, search as sam_search

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
        stripper = _HTMLStripper()
        stripper.feed(text)
        return stripper.get_text()
    return text


def _to_fields(opp: dict) -> dict:
    fields: dict = {}
    for dest_key, src_key in _FIELD_MAP.items():
        val = opp.get(src_key) or ""
        if dest_key == "Title":
            val = str(val)[:_TITLE_MAX]
        elif dest_key == "Description":
            val = _clean_description(str(val) if not isinstance(val, str) else val)
        fields[dest_key] = str(val) if not isinstance(val, str) else val

    notice_id = opp.get("noticeId", "")
    # Use uiLink from the official API if present, otherwise construct it
    fields["UiLink"] = opp.get("uiLink") or (_SAM_OPP_URL.format(notice_id) if notice_id else "")
    return fields


def run_sync(
    sam_api_key: str,
    profile: SearchProfile,
    poster: Poster,
    progress: Callable[[str], None] = print,
) -> SyncStats:
    progress(f'Searching SAM.gov: queries={profile.queries}')

    seen: set[str] = set()      # notice IDs from search window (for monitoring phase)
    emitted: set[str] = set()   # dedup across multiple queries

    whole_word_re = (
        re.compile(
            r"\b(" + "|".join(re.escape(q) for q in profile.queries) + r")\b",
            re.IGNORECASE,
        )
        if profile.whole_word else None
    )

    def _search_items():
        for query in profile.queries:
            for opp in sam_search(sam_api_key, profile.as_sam_params(query), progress=progress):
                if profile.active_only and opp.get("active", "").upper() != "YES":
                    continue
                if whole_word_re and not whole_word_re.search(opp.get("title", "") + " " + opp.get("description", "")):
                    continue
                notice_id = opp.get("noticeId")
                if notice_id:
                    seen.add(notice_id)
                    if notice_id in emitted:
                        continue
                    emitted.add(notice_id)
                yield _to_fields(opp)

    def _monitor_items():
        to_check = poster.active_notice_ids() - seen
        if not to_check:
            return
        progress(f"Re-checking {len(to_check)} tracked item(s) outside search window...")
        for notice_id in to_check:
            opp = fetch_by_id(sam_api_key, notice_id)
            if opp:
                yield _to_fields(opp)

    return poster.sync(chain(_search_items(), _monitor_items()), progress)
