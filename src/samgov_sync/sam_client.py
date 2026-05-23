"""SAM.gov search via SGS (full-text search, same backend as public website)."""

from __future__ import annotations

import re
import time
from random import choice
from string import digits
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlparse, unquote

import httpx

_SGS_BASE = "https://sam.gov/api/prod/sgs/v1/search/"
_PAGE_DELAY = 0.3


def _to_iso(mmddyyyy: str) -> str:
    m, d, y = mmddyyyy.split("/")
    return f"{y}-{m}-{d}T00:00:00-06:00"


def parse_sam_url(url: str) -> dict[str, Any]:
    """Parse a SAM.gov search URL into a normalised params dict."""
    pairs: dict[str, str] = {}
    for part in urlparse(url).query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs[unquote(k)] = unquote(v)
        else:
            pairs[unquote(part)] = ""

    tags: dict[int, str] = {}
    for k, v in pairs.items():
        m = re.match(r"sfm\[simpleSearch\]\[keywordTags\]\[(\d+)\]\[value\]$", k)
        if m:
            tags[int(m.group(1))] = v

    editor_q = pairs.get("sfm[simpleSearch][keywordEditorTextarea]", "").strip()
    result: dict[str, Any] = {
        "q":         editor_q if editor_q else " ".join(tags[i] for i in sorted(tags)),
        "q_mode":    pairs.get("sfm[simpleSearch][keywordRadio]", "ALL").upper(),
        "is_active": pairs.get("sfm[status][is_active]", "true").lower() == "true",
    }
    notice_type = pairs.get("sfm[notices][noticeType]")
    if notice_type:
        result["ptype"] = notice_type
    return result


def make_sgs_url(params: dict[str, Any], page: int = 0) -> str:
    """Build a paginated SGS request URL from a normalised params dict."""
    seed = "".join(choice(digits) for _ in range(13))
    is_active = str(params.get("is_active", True)).lower()
    url = (
        f"{_SGS_BASE}?random={seed}&index=opp"
        f"&page={page}&sort=-modifiedDate&size=1000"
        f"&mode=search&responseType=json"
        f"&qMode={params.get('q_mode', 'ALL')}&is_active={is_active}"
    )
    if params.get("postedFrom"):
        url += f"&modified_date.from={_to_iso(params['postedFrom'])}"
    if params.get("postedTo"):
        url += f"&modified_date.to={_to_iso(params['postedTo'])}"
    url += f"&q={params.get('q', '')}"
    if params.get("ptype"):
        url += f"&notice_type={params['ptype']}"
    return url


def search(
    sam_url: str,
    posted_from: str = "",
    posted_to: str = "",
    progress: Optional[Callable[[str], None]] = None,
) -> Iterator[dict[str, Any]]:
    """Yield every opportunity matching the SAM.gov search URL via the SGS endpoint."""
    
    params = parse_sam_url(sam_url)
    if posted_from: params["postedFrom"] = posted_from
    if posted_to:   params["postedTo"]   = posted_to
    
    page = 0
    while True:
        url = make_sgs_url(params, page)
        if page == 0 and progress:
            progress(f"  Parsed params: {params}")
            progress(f"  SGS query:     {url}")

        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        page_info = data.get("page", {})
        items = data.get("_embedded", {}).get("results", [])

        if not items:
            break

        total = page_info.get("totalElements", 0)
        fetched = page * 1000 + len(items)
        if progress:
            progress(f"  Fetching SAM.gov results: {fetched} / {total}")

        for item in items:
            yield _normalize(item)

        page += 1
        if page >= page_info.get("totalPages", 1):
            break

        time.sleep(_PAGE_DELAY)



def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    """Convert an SGS result to the same shape as the official API response."""
    org_hierarchy: list[dict[str, Any]] = item.get("organizationHierarchy") or []

    department: str = next(
        (o["name"] for o in org_hierarchy if o.get("level") == 1), ""
    )
    office_org: Optional[dict[str, Any]] = next(
        (o for o in reversed(org_hierarchy) if o.get("type") == "OFFICE"), None
    )
    office_address = ""
    if office_org:
        addr: dict[str, Any] = office_org.get("address") or {}
        parts: list[str] = [addr.get("city", ""), addr.get("state", ""), addr.get("zip", "")]
        office_address = ", ".join(p for p in parts if p)

    descriptions: list[dict[str, Any]] = item.get("descriptions") or []
    description: str = descriptions[0].get("content", "") if descriptions else ""

    opp_type = item.get("type", {})
    type_value: str = (
        opp_type.get("value", opp_type.get("code", ""))
        if isinstance(opp_type, dict)
        else str(opp_type)
    )

    return {
        "noticeId": item.get("_id", ""),
        "title": item.get("title", ""),
        "solicitationNumber": item.get("solicitationNumber", ""),
        "fullParentPathName": department,
        "officeAddress": office_address,
        "postedDate": (item.get("publishDate") or "")[:10],
        "responseDeadLine": (item.get("responseDate") or "")[:10],
        "typeOfSetAsideDescription": "",
        "naicsCode": "",
        "type": type_value,
        "active": "Yes" if item.get("isActive", True) else "No",
        "description": description,
    }
