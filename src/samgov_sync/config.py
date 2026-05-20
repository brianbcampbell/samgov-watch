"""
Environment-based credentials + TOML-based search profiles.

Credentials (.env):
    SAM_API_KEY                        — always required
    SP_TENANT_ID, SP_CLIENT_ID,        — required for --output sharepoint
      SP_CLIENT_SECRET, SP_SITE_ID,
      SP_LIST_ID
    DISCORD_BOT_TOKEN                  — required for --output discord
    DISCORD_CHANNEL_ID                 — forum channel ID for --output discord
    DISCORD_STATE_FILE                 — optional, default .discord_state.json

Search profiles (searches.toml):
    [[searches]]
    name = "my-search"
    query = "cybersecurity"
    posted_from = "01/01/2025"
    ...
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-reattr]


def _load_env(env_file: Optional[Path]) -> None:
    load_dotenv(env_file or Path(".env"))


def _require(keys: list[str]) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in the values."
        )


# ---------------------------------------------------------------------------
# Per-destination credential dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SamConfig:
    api_key: str

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "SamConfig":
        _load_env(env_file)
        _require(["SAM_API_KEY"])
        return cls(api_key=os.environ["SAM_API_KEY"])


@dataclass
class SharePointConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_id: str

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "SharePointConfig":
        _load_env(env_file)
        _require(["SP_TENANT_ID", "SP_CLIENT_ID", "SP_CLIENT_SECRET", "SP_SITE_ID"])
        return cls(
            tenant_id=os.environ["SP_TENANT_ID"],
            client_id=os.environ["SP_CLIENT_ID"],
            client_secret=os.environ["SP_CLIENT_SECRET"],
            site_id=os.environ["SP_SITE_ID"],
        )


@dataclass
class DiscordConfig:
    bot_token: str
    channel_id: Optional[str]   # fallback; profiles may override with discord_channel_id
    state_file: Path

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "DiscordConfig":
        _load_env(env_file)
        _require(["DISCORD_BOT_TOKEN"])
        return cls(
            bot_token=os.environ["DISCORD_BOT_TOKEN"],
            channel_id=os.getenv("DISCORD_CHANNEL_ID"),  # optional
            state_file=Path(os.getenv("DISCORD_STATE_FILE", "state/.discord_state.json")),
        )


# ---------------------------------------------------------------------------
# Search profile (from searches.toml)
# ---------------------------------------------------------------------------

@dataclass
class SearchProfile:
    name: str
    queries: list  # one or more search terms; all run against the same destination
    posted_from: Optional[str] = None
    posted_to: Optional[str] = None
    days_back: Optional[int] = None
    ptype: Optional[str] = None
    active_only: bool = True
    whole_word: bool = True
    discord_channel_id: Optional[str] = None
    sharepoint_list_id: Optional[str] = None
    q_mode: str = "EXACT"

    def _date_params(self) -> tuple:
        today = date.today()
        if self.days_back is not None:
            return (
                (today - timedelta(days=self.days_back)).strftime("%m/%d/%Y"),
                today.strftime("%m/%d/%Y"),
            )
        if self.posted_from:
            return self.posted_from, self.posted_to or today.strftime("%m/%d/%Y")
        return (
            (today - timedelta(days=90)).strftime("%m/%d/%Y"),
            today.strftime("%m/%d/%Y"),
        )

    def as_sam_params(self, query: str) -> dict:
        posted_from, posted_to = self._date_params()
        params = {
            "q": query,
            "q_mode": self.q_mode,
            "postedFrom": posted_from,
            "postedTo": posted_to,
        }
        if self.ptype:
            params["ptype"] = self.ptype
        return params

    @classmethod
    def from_dict(cls, data: dict) -> "SearchProfile":
        if "queries" in data:
            queries = [str(q) for q in data["queries"]]
        elif "query" in data:
            queries = [str(data["query"])]
        else:
            raise ValueError(f"Profile '{data.get('name', '?')}' must have 'query' or 'queries'")
        return cls(
            name=data["name"],
            queries=queries,
            posted_from=data.get("posted_from"),
            posted_to=data.get("posted_to"),
            days_back=int(data["days_back"]) if "days_back" in data else None,
            ptype=data.get("ptype"),
            active_only=bool(data.get("active_only", True)),
            whole_word=bool(data.get("whole_word", True)),
            discord_channel_id=str(data["discord_channel_id"]) if "discord_channel_id" in data else None,
            sharepoint_list_id=str(data["sharepoint_list_id"]) if "sharepoint_list_id" in data else None,
            q_mode=str(data.get("q_mode", "EXACT")).upper(),
        )


def load_profiles(path: Path) -> list[SearchProfile]:
    """Load all [[searches]] entries from a TOML file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Search config not found: {path}\n"
            "Copy searches.example.toml to searches.toml and define your searches."
        )
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("searches", [])
    if not entries:
        raise ValueError(f"No [[searches]] entries found in {path}")
    return [SearchProfile.from_dict(e) for e in entries]
