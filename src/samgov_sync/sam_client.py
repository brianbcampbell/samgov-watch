"""SAM.gov search via SGS (full-text) + official API for individual lookups."""

from __future__ import annotations

import time
from datetime import date, timedelta
from random import choice
from string import digits
from typing import Iterator, Optional

import httpx
import requests

_SGS_BASE = "https://sam.gov/api/prod/sgs/v1/search/"
_API_BASE = "https://api.sam.gov/opportunities/v2/search"
_PAGE_DELAY = 0.3


def _to_iso(mmddyyyy: str) -> str:
    """Convert MM/DD/YYYY to ISO 8601 with timezone for the SGS endpoint."""
    m, d, y = mmddyyyy.split("/")
    return f"{y}-{m}-{d}T00:00:00-06:00"


def search(
    api_key: str,
    params: dict,
    progress: Optional[callable] = None,
) -> Iterator[dict]:
    """
    Yield every opportunity matching *params* via SAM.gov full-text search.

    Uses the SGS endpoint (same one the SAM.gov website uses), so queries
    match against titles AND descriptions. No API key required for SGS.

    Recognised params:
        q           — search query (full text)
        q_mode      — ALL | ANY | EXACT (default EXACT)
        postedFrom  — MM/DD/YYYY
        postedTo    — MM/DD/YYYY
        ptype       — notice type code (o, k, r, p, a, s, u, g, i)
    """
    q = params.get("q", "")
    q_mode = params.get("q_mode", "EXACT")
    posted_from = params.get("postedFrom", "")
    posted_to = params.get("postedTo", "")
    ptype = params.get("ptype")

    page = 0
    while True:
        seed = "".join(choice(digits) for _ in range(13))
        url = (
            f"{_SGS_BASE}?random={seed}&index=opp"
            f"&page={page}&sort=-modifiedDate&size=1000"
            f"&mode=search&responseType=json&qMode={q_mode}&is_active=true"
        )
        if posted_from:
            url += f"&modified_date.from={_to_iso(posted_from)}"
        if posted_to:
            url += f"&modified_date.to={_to_iso(posted_to)}"
        url += f"&q={q}"
        if ptype:
            url += f"&notice_type={ptype}"

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


def fetch_by_id(api_key: str, notice_id: str) -> Optional[dict]:
    """Fetch a single opportunity by notice ID via the official API."""
    today = date.today()
    year_ago = today - timedelta(days=364)
    resp = requests.get(
        _API_BASE,
        params={
            "api_key": api_key,
            "noticeid": notice_id,
            "postedFrom": year_ago.strftime("%m/%d/%Y"),
            "postedTo": today.strftime("%m/%d/%Y"),
            "limit": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    opps = resp.json().get("opportunitiesData", [])
    return opps[0] if opps else None


def _normalize(item: dict) -> dict:
    """Convert an SGS result to the same shape as the official API response."""
    org_hierarchy = item.get("organizationHierarchy") or []

    department = next(
        (o["name"] for o in org_hierarchy if o.get("level") == 1), ""
    )
    office_org = next(
        (o for o in reversed(org_hierarchy) if o.get("type") == "OFFICE"), None
    )
    office_address = ""
    if office_org:
        addr = office_org.get("address", {})
        parts = [addr.get("city"), addr.get("state"), addr.get("zip")]
        office_address = ", ".join(p for p in parts if p)

    descriptions = item.get("descriptions", [])
    description = descriptions[0].get("content", "") if descriptions else ""

    opp_type = item.get("type", {})
    type_value = (
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
