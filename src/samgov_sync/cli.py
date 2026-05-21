"""CLI entry point for samgov-sync."""

from __future__ import annotations

import sys
from typing import Any, Optional

import requests as _requests
from rich.console import Console
from rich.table import Table

from .config import (
    CONFIG_FILE,
    AppConfig,
    DiscordConfig,
    OllamaConfig,
    SamConfig,
    SearchProfile,
    SharePointConfig,
    load_profiles,
    load_toml,
)
from .pipeline import Pipeline
from .posters import DiscordWriter, FileWriter, SharePointWriter, SyncStats, Writer

console = Console()

_DISCORD_API = "https://discord.com/api/v10"


def cli():
    """Search SAM.gov and sync results to a destination."""
    cfg, app_cfg, ollama_cfg = _load_config()
    sam_cfg, discord_cfg, sp_cfg = _load_credentials(cfg)
    profiles = _select_profiles(cfg, app_cfg)

    discord_cfg, sp_cfg = _startup_check(sam_cfg, ollama_cfg, discord_cfg, sp_cfg, profiles)

    profile_writers = _assemble_profile_writers(discord_cfg, sp_cfg, profiles)
    stats = _run_pipeline(sam_cfg, ollama_cfg, profile_writers)
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


def _load_credentials(cfg: dict[str, Any]) -> tuple[Optional[SamConfig], Optional[DiscordConfig], Optional[SharePointConfig]]:
    def _try(fn):
        try:
            return fn()
        except ValueError:
            return None

    return (
        _try(SamConfig.from_env),
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
    profile_writers: list[tuple[SearchProfile, list[Writer]]] = []

    for profile in profiles:
        dests = _dest_writers_for_profile(discord_cfg, sp_cfg, profile)
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
) -> list[Writer]:
    writers: list[Writer] = []

    if discord_cfg and profile.discord_channel_id:
        state_file = discord_cfg.state_file.with_stem(
            f"{discord_cfg.state_file.stem}_{profile.discord_channel_id}"
        )
        writers.append(DiscordWriter(discord_cfg.bot_token, profile.discord_channel_id, state_file))

    if sp_cfg and profile.sharepoint_list_id:
        writers.append(SharePointWriter(
            sp_cfg.tenant_id, sp_cfg.client_id, sp_cfg.client_secret,
            sp_cfg.site_id, profile.sharepoint_list_id,
        ))

    return writers


def _run_pipeline(
    sam_cfg: SamConfig,
    ollama_cfg: Optional[OllamaConfig],
    profile_writers: list[tuple[SearchProfile, list[Writer]]],
) -> SyncStats:
    all_writers = _unique_writers(profile_writers)
    pipeline = Pipeline(
        sam_api_key=sam_cfg.api_key,
        ollama_cfg=ollama_cfg,
        writers=all_writers,
        progress=console.print,
    )
    return pipeline.run_profiles(profile_writers)


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
    sam_cfg: Optional[SamConfig],
    ollama_cfg: Optional[OllamaConfig],
    discord_cfg: Optional[DiscordConfig],
    sp_cfg: Optional[SharePointConfig],
    profiles: list[SearchProfile],
) -> tuple[Optional[DiscordConfig], Optional[SharePointConfig]]:
    console.print("\n[bold]Startup[/bold]")

    _check_sam(sam_cfg)
    _check_ollama(ollama_cfg)
    discord_cfg = _check_discord(discord_cfg)
    sp_cfg = _check_sharepoint(sp_cfg)
    _print_profiles(profiles)

    console.print()
    return discord_cfg, sp_cfg


def _check_sam(sam_cfg: Optional[SamConfig]) -> None:
    console.print("\n  [bold]SAM.gov[/bold]")
    if sam_cfg:
        console.print("    API key      [green]present[/green]")
    else:
        console.print("    API key      [red]missing — set SAM_API_KEY in .env[/red]")
        sys.exit(1)


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
        GraphClient(sp_cfg.tenant_id, sp_cfg.client_id, sp_cfg.client_secret)._token()
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
