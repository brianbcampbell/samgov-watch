"""Ollama client for generating opportunity summaries."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Optional

import requests


def _strip_html(html: str) -> str:
    """Strip HTML tags to plain text for LLM input."""
    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)

    s = _Stripper()
    s.feed(html)
    text = " ".join(s.parts)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def summarize(host: str, model: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Ask Ollama to summarize an opportunity. Returns {"summary": str, "deliverables": [str]}
    or None if the server is unreachable or returns an error.
    """
    title = fields.get("Title", "")
    department = fields.get("Department", "")
    opp_type = fields.get("OpportunityType", "")
    raw = (fields.get("Description") or "").strip()
    description = _strip_html(raw) if raw else ""

    if not description:
        return {"summary": "", "deliverables": []}

    prompt = (
        "Summarize this US federal government contract opportunity from SAM.gov.\n\n"
        f"Title: {title}\n"
        f"Agency: {department}\n"
        f"Type: {opp_type}\n"
        f"Description:\n{description}\n\n"
        "Respond with valid JSON only — no markdown fences, no extra text:\n"
        '{"summary": "2-3 sentences: what is being procured, who needs it, notable scope or constraints", '
        '"deliverables": ["concrete deliverable 1", "concrete deliverable 2"]}'
    )

    try:
        resp = requests.post(
            f"{host.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"  [!] Ollama not reachable at {host} — skipping summarization")
        return None
    except requests.exceptions.HTTPError as exc:
        print(f"  [!] Ollama error: {exc} — skipping summarization")
        return None
    except requests.exceptions.Timeout:
        print(f"  [!] Ollama timed out — skipping summarization")
        return None

    try:
        text = resp.json().get("response", "")
        # Strip markdown fences if the model ignored the format instruction
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        return {
            "summary": str(data.get("summary", "")),
            "deliverables": [str(d) for d in data.get("deliverables", [])],
        }
    except Exception as exc:
        print(f"  [!] Ollama response parse error: {exc} — skipping summarization")
        return None
