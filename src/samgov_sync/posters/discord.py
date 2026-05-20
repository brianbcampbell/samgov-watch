"""Discord bot implementation of Poster — one forum thread per opportunity.

Requires a bot token (not a webhook) so the bot can post into a Forum channel.

Setup:
  1. discord.com/developers → New Application → Bot → copy token
  2. OAuth2 → URL Generator → scopes: bot
     permissions: Send Messages, Create Public Threads, Send Messages in Threads
  3. Invite the bot to your server
  4. Create a Forum channel, copy its ID (right-click → Copy Channel ID,
     requires Developer Mode in User Settings → Advanced)
  5. Set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in .env

Each opportunity becomes a named forum thread. The starter message contains
the full opportunity details as an embed. Updates edit that message in-place.
When SAM.gov marks an opportunity inactive, the embed turns grey and a message
is posted in the thread — users can then archive the thread manually when done.

Thread and message IDs are persisted in a local JSON state file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .base import Poster, fingerprint

_API = "https://discord.com/api/v10"
_BLUE = 0x0057A8    # new
_GOLD = 0xF0A500    # updated / active
_GREY = 0x8B9098    # closed / inactive


def _is_active(fields: dict) -> bool:
    return fields.get("Active", "Yes").upper() not in ("NO", "FALSE", "0", "")


class DiscordPoster(Poster):
    def __init__(self, bot_token: str, channel_id: str, state_file: Path):
        self._channel_id = channel_id
        self._state_file = state_file
        self._headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        self._state: dict[str, dict] = _load_json(state_file)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a Discord API request, retrying automatically on rate limit."""
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

    # ------------------------------------------------------------------
    # Poster interface
    # ------------------------------------------------------------------

    def active_notice_ids(self) -> set[str]:
        return {nid for nid, entry in self._state.items() if entry.get("active", True)}

    def _load_existing(self) -> dict[str, tuple[str, str]]:
        # Use notice_id as backend_id so _update can look up thread_id
        # and message_id from self._state.
        return {
            nid: (entry["fingerprint"], nid)
            for nid, entry in self._state.items()
        }

    def _create(self, fields: dict) -> None:
        url = f"{_API}/channels/{self._channel_id}/threads"
        body = {
            "name": fields.get("Title", "SAM.gov Opportunity")[:100],
            "message": {"embeds": [_build_embed(fields, _BLUE)]},
            "auto_archive_duration": 10080,  # Discord auto-archives after 7 days of no activity
        }
        data = self._request("POST", url, json=body).json()
        thread_id = data["id"]
        message_id = data.get("message", {}).get("id", thread_id)
        self._state[fields["NoticeId"]] = {
            "thread_id": thread_id,
            "message_id": message_id,
            "fingerprint": fingerprint(fields),
            "active": True,
        }
        _save_json(self._state_file, self._state)

    def _update(self, notice_id: str, fields: dict) -> None:
        entry = self._state[notice_id]
        was_active = entry.get("active", True)
        now_active = _is_active(fields)

        color = _GOLD if now_active else _GREY
        msg_url = f"{_API}/channels/{entry['thread_id']}/messages/{entry['message_id']}"
        self._request("PATCH", msg_url, json={"embeds": [_build_embed(fields, color)]})

        if was_active and not now_active:
            note_url = f"{_API}/channels/{entry['thread_id']}/messages"
            self._request("POST", note_url, json={"content": "This opportunity has been closed on SAM.gov."})

        entry["fingerprint"] = fingerprint(fields)
        entry["active"] = now_active
        _save_json(self._state_file, self._state)


# ------------------------------------------------------------------
# Embed builder
# ------------------------------------------------------------------

def _build_embed(fields: dict, color: int) -> dict:
    def f(key: str) -> str:
        return fields.get(key) or "—"

    embed: dict = {
        "color": color,
        "title": fields.get("Title", "SAM.gov Opportunity")[:256],
        "fields": [
            {"name": "Notice ID",          "value": f("NoticeId"),           "inline": True},
            {"name": "Solicitation #",      "value": f("SolicitationNumber"), "inline": True},
            {"name": "Type",                "value": f("OpportunityType"),    "inline": True},
            {"name": "Posted",              "value": f("PostedDate"),         "inline": True},
            {"name": "Response Deadline",   "value": f("ResponseDeadline"),   "inline": True},
            {"name": "Active",              "value": f("Active"),             "inline": True},
            {"name": "Set-Aside",           "value": f("SetAside"),           "inline": True},
            {"name": "NAICS Code",          "value": f("NaicsCode"),          "inline": True},
            {"name": "Office",              "value": f("OfficeAddress"),      "inline": True},
            {"name": "Department",          "value": f("Department"),         "inline": False},
        ],
        "footer": {"text": "SAM.gov"},
    }

    ui_link = fields.get("UiLink")
    if ui_link:
        embed["url"] = ui_link

    description = (fields.get("Description") or "").strip()
    if description:
        embed["description"] = description[:4096]

    return embed


# ------------------------------------------------------------------
# State file helpers
# ------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
