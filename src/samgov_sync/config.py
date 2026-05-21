"""
Config loading for samgov-sync.

Secrets (.env — never commit):
    SAM_API_KEY                 — always required
    DISCORD_BOT_TOKEN           — required for output = "discord"
    SP_TENANT_ID, SP_CLIENT_ID,
      SP_CLIENT_SECRET, SP_SITE_ID  — required for output = "sharepoint"

Non-secret config (config.toml):
    [app]
        output = "discord"          # discord | sharepoint (default discord)
        profile = "my-profile"      # optional; run only this named profile

    [discord]
        state_file = "state/.discord_state.json"
        worker_threads = 8

    [ollama]
        host = "http://machine3.local:11434"
        model = "gemma4"

    [[searches]]
        name = "..."
        query = "..."
        ...
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-reattr]

CONFIG_FILE = Path("config.toml")
_ENV_FILE = Path(".env")


def load_toml(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}\n"
            "Create config.toml with [app], [discord]/[ollama] sections and [[searches]] entries."
        )
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _load_env() -> None:
    load_dotenv(_ENV_FILE)


def _require(keys: list[str]) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in the values."
        )


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    profile: Optional[str]  # None = run all profiles

    @classmethod
    def from_toml(cls, data: dict[str, Any]) -> "AppConfig":
        app = data.get("app", {})
        return cls(
            profile=app.get("profile") or None,
        )


@dataclass
class SamConfig:
    api_key: str

    @classmethod
    def from_env(cls) -> "SamConfig":
        _load_env()
        _require(["SAM_API_KEY"])
        return cls(api_key=os.environ["SAM_API_KEY"])


@dataclass
class SharePointConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_id: str

    @classmethod
    def from_env(cls) -> "SharePointConfig":
        _load_env()
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
    state_file: Path

    @classmethod
    def from_toml_and_env(cls, data: dict[str, Any]) -> "DiscordConfig":
        _load_env()
        _require(["DISCORD_BOT_TOKEN"])
        discord = data.get("discord", {})
        return cls(
            bot_token=os.environ["DISCORD_BOT_TOKEN"],
            state_file=Path(discord.get("state_file", "state/.discord_state.json")),
        )


@dataclass
class OllamaConfig:
    host: str
    model: str

    @classmethod
    def from_toml(cls, data: dict[str, Any]) -> Optional["OllamaConfig"]:
        """Return config if [ollama] host is set, else None."""
        ollama = data.get("ollama", {})
        host = ollama.get("host", "").strip()
        if not host:
            return None
        return cls(
            host=host,
            model=ollama.get("model", "gemma4"),
        )


# ---------------------------------------------------------------------------
# Search profile (from [[searches]] in config.toml)
# ---------------------------------------------------------------------------

@dataclass
class SearchProfile:
    name: str
    queries: list[str]
    posted_from: Optional[str] = None
    posted_to: Optional[str] = None
    days_back: Optional[int] = None
    ptype: Optional[str] = None
    active_only: bool = True
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

    def as_sam_params(self, query: str) -> dict[str, str]:
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
    def from_dict(cls, data: dict[str, Any]) -> "SearchProfile":
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
            discord_channel_id=str(data["discord_channel_id"]) if "discord_channel_id" in data else None,
            sharepoint_list_id=str(data["sharepoint_list_id"]) if "sharepoint_list_id" in data else None,
            q_mode=str(data.get("q_mode", "EXACT")).upper(),
        )


def load_profiles(data: dict[str, Any]) -> list[SearchProfile]:
    """Load all [[searches]] entries from an already-parsed config dict."""
    entries = data.get("searches", [])
    if not entries:
        raise ValueError("No [[searches]] entries found in config.toml")
    return [SearchProfile.from_dict(e) for e in entries]
