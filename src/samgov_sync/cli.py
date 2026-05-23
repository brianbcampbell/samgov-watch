"""CLI entry point for samgov-sync."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests as _requests
from rich.console import Console
from rich.table import Table

from .config import (
    CONFIG_FILE,
    AppConfig,
    DiscordConfig,
    OllamaConfig,
    SearchProfile,
    SharePointConfig,
    load_profiles,
    load_toml,
)
from .pipeline import Pipeline
from .posters import DiscordWriter, FileWriter, SharePointWriter, SyncStats, Writer
from .sam_client import search as sam_search

console = Console()

_DISCORD_API = "https://discord.com/api/v10"


def cli():
    """Search SAM.gov and sync results to a destination."""
    cfg, app_cfg, ollama_cfg = _load_config()
    profiles = _select_profiles(cfg, app_cfg)

    if app_cfg.query_only:
        _run_query_only(profiles)
        return

    discord_cfg, sp_cfg = _load_credentials(cfg)
    discord_cfg, sp_cfg = _startup_check(ollama_cfg, discord_cfg, sp_cfg, profiles)

    profile_writers = _assemble_profile_writers(discord_cfg, sp_cfg, profiles)
    stats = _run_pipeline(ollama_cfg, profile_writers)
    _print_stats(stats)


# ------------------------------------------------------------------
# Setup steps
# ------------------------------------------------------------------

def _load_config() -> tuple[dict[str, Any], AppConfig, Optional[OllamaConfig]]:
    try:
        cfg = load_toml(CONFIG_FILE)
        return cfg, AppConfig.from_toml(cfg), OllamaConfig.from_toml(cfg)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)


def _load_credentials(cfg: dict[str, Any]) -> tuple[Optional[DiscordConfig], Optional[SharePointConfig]]:
    def _try(fn):
        try:
            return fn()
        except ValueError:
            return None

    return (
        _try(lambda: DiscordConfig.from_toml_and_env(cfg)),
        _try(SharePointConfig.from_env),
    )


def _select_profiles(cfg: dict[str, Any], app_cfg: AppConfig) -> list[SearchProfile]:
    try:
        profiles = load_profiles(cfg)
    except ValueError as exc:
        console.print(f"[red]Search config error:[/red] {exc}")
        sys.exit(1)

    if app_cfg.profile:
        profiles = [p for p in profiles if p.name == app_cfg.profile]
        if not profiles:
            console.print(f"[red]No profile named '{app_cfg.profile}' in config.toml[/red]")
            sys.exit(1)

    return profiles


def _assemble_profile_writers(
    discord_cfg: Optional[DiscordConfig],
    sp_cfg: Optional[SharePointConfig],
    profiles: list[SearchProfile],
) -> list[tuple[SearchProfile, list[Writer]]]:
    file_writer = FileWriter()
    discord_writers: dict[str, DiscordWriter] = {}
    sp_writers: dict[str, SharePointWriter] = {}
    profile_writers: list[tuple[SearchProfile, list[Writer]]] = []

    for profile in profiles:
        dests = _dest_writers_for_profile(discord_cfg, sp_cfg, profile, discord_writers, sp_writers)
        if dests:
            profile_writers.append((profile, [file_writer, *dests]))

    if not profile_writers:
        console.print("[yellow]No profiles with configured destinations.[/yellow]")
        sys.exit(0)

    return profile_writers


def _dest_writers_for_profile(
    discord_cfg: Optional[DiscordConfig],
    sp_cfg: Optional[SharePointConfig],
    profile: SearchProfile,
    discord_writers: dict[str, DiscordWriter],
    sp_writers: dict[str, SharePointWriter],
) -> list[Writer]:
    writers: list[Writer] = []

    if discord_cfg and profile.discord_channel_id:
        cid = profile.discord_channel_id
        if cid not in discord_writers:
            discord_writers[cid] = DiscordWriter(
                discord_cfg.bot_token, cid,
                Path(f"state/.discord_state_{cid}.json"),
            )
        writers.append(discord_writers[cid])

    if sp_cfg and profile.sharepoint_list_id:
        lid = profile.sharepoint_list_id
        if lid not in sp_writers:
            sp_writers[lid] = SharePointWriter(
                sp_cfg.tenant_id, sp_cfg.client_id, sp_cfg.client_secret,
                sp_cfg.site_id, lid,
            )
        writers.append(sp_writers[lid])

    return writers


def _run_pipeline(
    ollama_cfg: Optional[OllamaConfig],
    profile_writers: list[tuple[SearchProfile, list[Writer]]],
) -> SyncStats:
    all_writers = _unique_writers(profile_writers)
    pipeline = Pipeline(
        ollama_cfg=ollama_cfg,
        writers=all_writers,
        progress=console.print,
    )
    return pipeline.run_profiles(profile_writers)


def _run_query_only(profiles: list[SearchProfile]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("state/query")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"query_{timestamp}.json"
    entries: list[dict[str, Any]] = []

    for profile in profiles:
        console.print(f"  [{profile.name}] {profile.url}")
        posted_from, posted_to = profile.date_range()
        results = list(sam_search(profile.url, posted_from, posted_to, progress=console.print))
        console.print(f"    → {len(results)} results")
        entries.append({"profile": profile.name, "url": profile.url, "results": results})

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
    console.print(f"\n[green]Saved {out_path}[/green]")


def _unique_writers(profile_writers: list[tuple[SearchProfile, list[Writer]]]) -> list[Writer]:
    seen: set[int] = set()
    result: list[Writer] = []
    for _, writers in profile_writers:
        for w in writers:
            if id(w) not in seen:
                result.append(w)
                seen.add(id(w))
    return result


# ------------------------------------------------------------------
# Startup check
# ------------------------------------------------------------------

def _startup_check(
    ollama_cfg: Optional[OllamaConfig],
    discord_cfg: Optional[DiscordConfig],
    sp_cfg: Optional[SharePointConfig],
    profiles: list[SearchProfile],
) -> tuple[Optional[DiscordConfig], Optional[SharePointConfig]]:
    console.print("\n[bold]Startup[/bold]")

    _check_ollama(ollama_cfg)
    discord_cfg = _check_discord(discord_cfg)
    sp_cfg = _check_sharepoint(sp_cfg)
    _print_profiles(profiles)

    console.print()
    return discord_cfg, sp_cfg


def _check_ollama(ollama_cfg: Optional[OllamaConfig]) -> None:
    console.print("\n  [bold]LLM (Ollama)[/bold]")
    if not ollama_cfg:
        console.print("    Server       [dim]not configured (summaries disabled)[/dim]")
        return
    try:
        resp = _requests.get(f"{ollama_cfg.host.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        model_found = any(ollama_cfg.model in n for n in names)
        if model_found:
            console.print(f"    Server       [green]ready[/green] ({ollama_cfg.model} @ {ollama_cfg.host})")
        else:
            console.print(f"    Server       [yellow]connected — model '{ollama_cfg.model}' not found[/yellow]")
    except Exception:
        console.print(f"    Server       [yellow]not reachable ({ollama_cfg.host}) — summaries disabled[/yellow]")


def _check_discord(discord_cfg: Optional[DiscordConfig]) -> Optional[DiscordConfig]:
    console.print("\n  [bold]Discord[/bold]")
    if not discord_cfg:
        console.print("    Bot token    [yellow]missing — disabled[/yellow]")
        return None
    console.print("    Bot token    [green]present[/green]")
    try:
        resp = _requests.get(
            f"{_DISCORD_API}/users/@me",
            headers={"Authorization": f"Bot {discord_cfg.bot_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        console.print(f"    Connection   [green]connected[/green] (Bot: {resp.json().get('username', '?')})")
        return discord_cfg
    except Exception as exc:
        console.print(f"    Connection   [red]failed — disabled[/red] ({exc})")
        return None


def _check_sharepoint(sp_cfg: Optional[SharePointConfig]) -> Optional[SharePointConfig]:
    console.print("\n  [bold]SharePoint[/bold]")
    if not sp_cfg:
        console.print("    Credentials  [yellow]missing — disabled[/yellow]")
        return None
    console.print("    Credentials  [green]present[/green]")
    try:
        from .graph_client import GraphClient
        GraphClient(sp_cfg.tenant_id, sp_cfg.client_id, sp_cfg.client_secret).token()
        console.print("    Connection   [green]authenticated[/green]")
        return sp_cfg
    except Exception as exc:
        console.print(f"    Connection   [red]failed — disabled[/red] ({exc})")
        return None


def _print_profiles(profiles: list[SearchProfile]) -> None:
    console.print("\n  [bold]Search profiles[/bold]")
    for p in profiles:
        d = p.discord_channel_id or "—"
        s = p.sharepoint_list_id or "—"
        console.print(f"    {p.name:<20} discord: {d:<22} sharepoint: {s}")
        console.print(f"    {'':20} url: {p.url[:80]}")


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------

def _print_stats(stats: SyncStats) -> None:
    table = Table(title="Sync Results")
    table.add_column("Action", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    table.add_row("Created", str(stats.created))
    table.add_row("Updated", str(stats.updated))
    table.add_row("Skipped (unchanged)", str(stats.skipped))
    if stats.errors:
        table.add_row("[red]Errors[/red]", f"[red]{stats.errors}[/red]")
    console.print(table)
