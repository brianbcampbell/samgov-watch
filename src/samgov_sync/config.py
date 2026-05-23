"""
Config loading for samgov-sync.

Secrets (.env — never commit):
    DISCORD_BOT_TOKEN           — required for Discord output
    SP_TENANT_ID, SP_CLIENT_ID,
      SP_CLIENT_SECRET, SP_SITE_ID  — required for SharePoint output

Non-secret config (config.toml):
    [app]
        profile = "my-profile"      # optional; run only this named profile

    [ollama]
        host = "http://machine3.local:11434"
        model = "gemma4"

    [[search]]
        name = "..."
        url  = "https://sam.gov/search/?..."
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
            "Create config.toml with [app], [discord]/[ollama] sections and [[search]] entries."
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
    query_only: bool = False

    @classmethod
    def from_toml(cls, data: dict[str, Any]) -> "AppConfig":
        app = data.get("app", {})
        return cls(
            profile=app.get("profile") or None,
            query_only=bool(app.get("query_only", False)),
        )


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

    @classmethod
    def from_toml_and_env(cls, _data: dict[str, Any]) -> "DiscordConfig":
        _load_env()
        _require(["DISCORD_BOT_TOKEN"])
        return cls(bot_token=os.environ["DISCORD_BOT_TOKEN"])


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
# Search profile (from [[search]] in config.toml)
# ---------------------------------------------------------------------------

@dataclass
class SearchProfile:
    name: str
    url: str
    posted_from: Optional[str] = None
    posted_to: Optional[str] = None
    days_back: Optional[int] = None
    discord_channel_id: Optional[str] = None
    sharepoint_list_id: Optional[str] = None

    def _date_params(self) -> tuple[str, str]:
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

    def date_range(self) -> tuple[str, str]:
        return self._date_params()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchProfile":
        if "url" not in data:
            raise ValueError(f"Profile '{data.get('name', '?')}' must have a 'url' field (paste a SAM.gov search URL)")
        return cls(
            name=data["name"],
            url=data["url"],
            posted_from=data.get("posted_from"),
            posted_to=data.get("posted_to"),
            days_back=int(data["days_back"]) if "days_back" in data else None,
            discord_channel_id=str(data["discord_channel_id"]) if "discord_channel_id" in data else None,
            sharepoint_list_id=str(data["sharepoint_list_id"]) if "sharepoint_list_id" in data else None,
        )


def load_profiles(data: dict[str, Any]) -> list[SearchProfile]:
    """Load all [[search]] entries from an already-parsed config dict."""
    entries = data.get("search", [])
    if not entries:
        raise ValueError("No [[search]] entries found in config.toml")
    return [SearchProfile.from_dict(e) for e in entries]
