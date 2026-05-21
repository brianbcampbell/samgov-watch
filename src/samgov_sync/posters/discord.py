"""Discord writer — one forum thread per opportunity.

Each opportunity becomes a named forum thread with:
  1. An embed with structured fields (type, dates, agency, link).
  2. The description as a plain-text reply (truncated at 2000 chars).
  3. An AI summary reply if the item was enriched by Ollama.

Updates edit messages in-place. Closing turns the embed grey, posts a
notice, and adds a ❌ reaction to the embed message.

Thread/message IDs are persisted in state/.discord_state_{channel_id}.json.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import markdownify
import requests

from .base import Writer, SyncStats, fingerprint, is_closed

_API = "https://discord.com/api/v10"
_BLUE = 0x0057A8    # new
_GOLD = 0xF0A500    # updated / active
_GREY = 0x8B9098    # closed / inactive

_MSG_LIMIT = 2000


class _WriteQueue:
    """Serialises write tasks on a single background thread.

    put() may be called from the main thread while tasks execute on the
    background thread. drain() blocks until the queue is empty.
    """

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="discord-writer")
        self._thread.start()

    def _run(self) -> None:
        while True:
            task = self._q.get()
            try:
                task()
            except Exception as exc:
                print(f"  [!] Discord write error: {exc}")
            finally:
                self._q.task_done()

    def put(self, task: Callable[[], None]) -> None:
        self._q.put(task)

    def drain(self) -> None:
        self._q.join()


def _truncate_desc(text: str, ui_link: str) -> str:
    text = text.strip()
    if len(text) <= _MSG_LIMIT:
        return text
    suffix = f"\n… [full text →]({ui_link})" if ui_link else "\n… *(truncated)*"
    return text[:_MSG_LIMIT - len(suffix)] + suffix


class DiscordWriter(Writer):
    def __init__(self, bot_token: str, channel_id: str, state_file: Path):
        super().__init__()
        if not bot_token:
            raise ValueError("DISCORD_BOT_TOKEN is required")
        self._channel_id = channel_id
        self._state_file = state_file
        self._headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        self._state: dict[str, dict[str, Any]] = _load_json(state_file)
        self._write_queue = _WriteQueue()
        self._state_lock = threading.Lock()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        while True:
            resp = requests.request(method, url, headers=self._headers, timeout=15, **kwargs)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 1)
                time.sleep(float(retry_after))
                continue
            resp.raise_for_status()
            return resp

    @property
    def name(self) -> str:
        return "Discord"

    def active_ids(self) -> set[str]:
        return {nid for nid, entry in self._state.items() if entry.get("active", True)}

    def _load_existing(self) -> dict[str, tuple[str, str]]:
        return {nid: (entry["fingerprint"], nid) for nid, entry in self._state.items()}

    def flush(self) -> None:
        self._write_queue.drain()

    # ------------------------------------------------------------------
    # Writer interface
    # ------------------------------------------------------------------

    def _create(self, fields: dict[str, Any]) -> None:
        def _task() -> None:
            if not self._channel_id:
                return
            closed = is_closed(fields)
            color = _GREY if closed else _BLUE
            url = f"{_API}/channels/{self._channel_id}/threads"
            body = {
                "name": fields.get("Title", "SAM.gov Opportunity")[:100],
                "message": {"embeds": [_build_embed(fields, color)]},
                "auto_archive_duration": 10080,
            }
            try:
                data = self._request("POST", url, json=body).json()
            except Exception as exc:
                print(f"  [!] {fields.get('NoticeId')}: create failed — {exc}")
                return
            thread_id = data["id"]
            message_id = data.get("message", {}).get("id", thread_id)
            entry: dict[str, Any] = {
                "thread_id": thread_id,
                "message_id": message_id,
                "fingerprint": fingerprint(fields),
                "active": not closed,
            }
            _post_description(self, thread_id, fields, entry)
            _post_or_update_summary(self, thread_id, fields, entry)
            with self._state_lock:
                self._state[fields["NoticeId"]] = entry
                _save_json(self._state_file, self._state)
            if closed:
                self.set_closed(fields["NoticeId"], fields)

        self._write_queue.put(_task)

    def _update(self, notice_id: str, fields: dict[str, Any]) -> None:
        def _task() -> None:
            if not self._channel_id:
                return
            entry = self._state[notice_id]
            was_closed = not entry.get("active", True)
            closed = is_closed(fields)
            color = _GREY if closed else _GOLD
            try:
                msg_url = f"{_API}/channels/{entry['thread_id']}/messages/{entry['message_id']}"
                self._request("PATCH", msg_url, json={"embeds": [_build_embed(fields, color)]})
            except Exception as exc:
                print(f"  [!] {notice_id}: update failed — {exc}")
                return
            _update_description(self, entry, fields)
            _post_or_update_summary(self, entry["thread_id"], fields, entry)
            with self._state_lock:
                entry["fingerprint"] = fingerprint(fields)
                entry["active"] = not closed
                _save_json(self._state_file, self._state)
            if not was_closed and closed:
                self.set_closed(notice_id, fields)
            elif was_closed and not closed:
                self.set_reopened(notice_id, fields)

        self._write_queue.put(_task)

    def set_closed(self, notice_id: str, fields: dict[str, Any]) -> None:
        """Closing notice + ❌ reaction. Called from within the write queue thread."""
        entry = self._state.get(notice_id)
        if not entry:
            return
        thread_id = entry["thread_id"]
        try:
            resp = self._request(
                "POST",
                f"{_API}/channels/{thread_id}/messages",
                json={"content": "This opportunity has been closed on SAM.gov."},
            )
            with self._state_lock:
                entry["closing_message_id"] = resp.json().get("id")
                _save_json(self._state_file, self._state)
        except Exception as exc:
            print(f"  [!] {notice_id}: closing notice failed — {exc}")
        _add_closed_reaction(self, thread_id, entry["message_id"])

    def set_reopened(self, notice_id: str, fields: dict[str, Any]) -> None:
        """Remove ❌ reaction and closing notice when a previously-closed item reappears."""
        entry = self._state.get(notice_id)
        if not entry:
            return
        thread_id = entry["thread_id"]
        emoji = urllib.parse.quote("❌")
        try:
            self._request("DELETE", f"{_API}/channels/{thread_id}/messages/{entry['message_id']}/reactions/{emoji}/@me")
        except Exception as exc:
            print(f"  [!] {notice_id}: remove reaction failed — {exc}")
        closing_msg = entry.get("closing_message_id")
        if closing_msg:
            try:
                self._request("DELETE", f"{_API}/channels/{thread_id}/messages/{closing_msg}")
                with self._state_lock:
                    del entry["closing_message_id"]
                    _save_json(self._state_file, self._state)
            except Exception as exc:
                print(f"  [!] {notice_id}: delete closing notice failed — {exc}")


# ------------------------------------------------------------------
# Summary helpers
# ------------------------------------------------------------------

def _post_or_update_summary(poster: DiscordWriter, thread_id: str, fields: dict[str, Any], entry: dict[str, Any]) -> None:
    summary = (fields.get("Summary") or "").strip()
    if not summary:
        return
    deliverables = fields.get("Deliverables") or []
    content = f"**Summary**\n{summary}"
    if deliverables:
        content += "\n\n**Deliverables**\n" + "\n".join(f"- {d}" for d in deliverables)
    fp = hashlib.md5(content.encode()).hexdigest()
    if fp == entry.get("summary_fingerprint"):
        return
    try:
        if "summary_message_id" in entry:
            poster._request(
                "PATCH",
                f"{_API}/channels/{thread_id}/messages/{entry['summary_message_id']}",
                json={"content": content},
            )
        else:
            msg = poster._request(
                "POST", f"{_API}/channels/{thread_id}/messages", json={"content": content}
            ).json()
            entry["summary_message_id"] = msg["id"]
        entry["summary_fingerprint"] = fp
    except Exception as exc:
        print(f"  [!] summary post failed — {exc}")


# ------------------------------------------------------------------
# Reaction helpers
# ------------------------------------------------------------------

def _add_closed_reaction(poster: DiscordWriter, thread_id: str, message_id: str) -> None:
    emoji = urllib.parse.quote("❌")
    url = f"{_API}/channels/{thread_id}/messages/{message_id}/reactions/{emoji}/@me"
    try:
        poster._request("PUT", url)
    except Exception as exc:
        print(f"  [!] reaction failed — {exc}")


# ------------------------------------------------------------------
# Description reply helpers
# ------------------------------------------------------------------

def _post_description(poster: DiscordWriter, thread_id: str, fields: dict[str, Any], entry: dict[str, Any]) -> None:
    raw = fields.get("Description", "")
    desc = _truncate_desc(_to_markdown(raw), fields.get("UiLink", ""))
    if not desc:
        return
    msg = poster._request("POST", f"{_API}/channels/{thread_id}/messages", json={"content": desc}).json()
    entry["description_message_id"] = msg["id"]
    entry["description_fingerprint"] = _desc_fp(raw)


def _update_description(poster: DiscordWriter, entry: dict[str, Any], fields: dict[str, Any]) -> None:
    raw = fields.get("Description", "")
    desc = _truncate_desc(_to_markdown(raw), fields.get("UiLink", ""))
    new_fp = _desc_fp(raw)
    if new_fp == entry.get("description_fingerprint") and "description_message_id" in entry:
        return
    thread_id = entry["thread_id"]
    if "description_message_id" in entry:
        url = f"{_API}/channels/{thread_id}/messages/{entry['description_message_id']}"
        try:
            poster._request("PATCH", url, json={"content": desc})
        except Exception:
            del entry["description_message_id"]
            _post_description(poster, thread_id, fields, entry)
            return
    else:
        _post_description(poster, thread_id, fields, entry)
        return
    entry["description_fingerprint"] = new_fp


def _desc_fp(text: str) -> str:
    return hashlib.md5(text.strip().encode()).hexdigest()


# ------------------------------------------------------------------
# HTML → markdown
# ------------------------------------------------------------------

def _to_markdown(html: str) -> str:
    if not html:
        return ""
    md = markdownify.markdownify(html, heading_style="ATX", bullets="-")
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.replace("||", "|​|")  # zero-width space breaks Discord spoiler syntax
    return md.strip()


# ------------------------------------------------------------------
# Embed builder
# ------------------------------------------------------------------

def _build_embed(fields: dict[str, Any], color: int) -> dict[str, Any]:
    def f(key: str) -> str:
        return fields.get(key) or "—"

    embed: dict[str, Any] = {
        "color": color,
        "title": fields.get("Title", "SAM.gov Opportunity")[:256],
        "fields": [
            {"name": "Notice ID",          "value": f("NoticeId"),           "inline": False},
            {"name": "Solicitation #",      "value": f("SolicitationNumber"), "inline": False},
            {"name": "Type",                "value": f("OpportunityType"),    "inline": False},
            {"name": "Posted",              "value": f("PostedDate"),         "inline": False},
            {"name": "Response Deadline",   "value": f("ResponseDeadline"),   "inline": False},
            {"name": "Active",              "value": f("Active"),             "inline": False},
            {"name": "Set-Aside",           "value": f("SetAside"),           "inline": False},
            {"name": "NAICS Code",          "value": f("NaicsCode"),          "inline": False},
            {"name": "Office",              "value": f("OfficeAddress"),      "inline": False},
            {"name": "Department",          "value": f("Department"),         "inline": False},
        ],
        "footer": {"text": "SAM.gov"},
    }
    ui_link = fields.get("UiLink", "")
    if ui_link:
        embed["url"] = ui_link
    return embed


# ------------------------------------------------------------------
# State file helpers
# ------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
