"""CLI entry point for samgov-sync."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import DiscordConfig, SamConfig, SearchProfile, SharePointConfig, load_profiles
from .graph_client import GraphClient
from .posters import DiscordPoster, Poster, SharePointPoster, SyncStats
from .sam_client import search as sam_search
from .sync import _to_fields, run_sync

console = Console()

DEFAULT_SEARCHES_FILE = Path("searches.toml")
DEFAULT_ENV_FILE = Path(".env")

OUTPUT_CHOICES = click.Choice(["sharepoint", "discord"], case_sensitive=False)


@click.group()
def cli():
    """Search SAM.gov and sync results to a destination."""


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--output", "-o",
    type=OUTPUT_CHOICES,
    default="sharepoint",
    show_default=True,
    help="Destination to post results to.",
)
@click.option(
    "--searches",
    "searches_file",
    type=click.Path(path_type=Path),
    default=DEFAULT_SEARCHES_FILE,
    show_default=True,
)
@click.option(
    "--profile",
    "profile_name",
    default=None,
    help="Run only this named profile (default: run all).",
)
@click.option(
    "--env",
    "env_file",
    type=click.Path(path_type=Path),
    default=DEFAULT_ENV_FILE,
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Print results without writing anywhere.")
def sync(
    output: str,
    searches_file: Path,
    profile_name: str | None,
    env_file: Path,
    dry_run: bool,
):
    """Run search profiles and sync results to the chosen destination."""
    try:
        sam_cfg = SamConfig.from_env(env_file)
        sp_cfg = SharePointConfig.from_env(env_file) if output == "sharepoint" else None
        discord_cfg = DiscordConfig.from_env(env_file) if output == "discord" else None
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise SystemExit(1)

    try:
        profiles = load_profiles(searches_file)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Search config error:[/red] {exc}")
        raise SystemExit(1)

    if profile_name:
        profiles = [p for p in profiles if p.name == profile_name]
        if not profiles:
            console.print(f"[red]No profile named '{profile_name}' in {searches_file}[/red]")
            raise SystemExit(1)

    if dry_run:
        _run_dry(sam_cfg.api_key, profiles)
        return

    totals = SyncStats()
    for profile in profiles:
        console.rule(f"[bold]{profile.name}[/bold]")
        poster = _build_poster(output, sp_cfg, discord_cfg, profile)
        totals += run_sync(sam_cfg.api_key, profile, poster, progress=console.print)

    _print_stats(totals)


def _build_poster(
    output: str,
    sp_cfg: "SharePointConfig | None",
    discord_cfg: "DiscordConfig | None",
    profile: SearchProfile,
) -> Poster:
    if output == "sharepoint":
        list_id = profile.sharepoint_list_id
        if not list_id:
            raise ValueError(
                f"Profile '{profile.name}' has no sharepoint_list_id in searches.toml"
            )
        return SharePointPoster(
            sp_cfg.tenant_id, sp_cfg.client_id, sp_cfg.client_secret,
            sp_cfg.site_id, list_id,
        )
    if output == "discord":
        channel_id = profile.discord_channel_id or discord_cfg.channel_id
        if not channel_id:
            raise ValueError(
                f"Profile '{profile.name}' has no discord_channel_id and "
                "DISCORD_CHANNEL_ID is not set in .env"
            )
        state_file = discord_cfg.state_file.with_stem(
            f"{discord_cfg.state_file.stem}_{channel_id}"
        )
        return DiscordPoster(discord_cfg.bot_token, channel_id, state_file)
    raise ValueError(f"Unknown output: {output}")


def _run_dry(api_key: str, profiles: list[SearchProfile]) -> None:
    console.print("[yellow]DRY RUN[/yellow] — no data will be written\n")
    total = 0
    seen: set[str] = set()
    for profile in profiles:
        console.rule(f"[bold]{profile.name}[/bold]")
        console.print(f'queries={profile.queries}')
        for query in profile.queries:
            for opp in sam_search(api_key, profile.as_sam_params(query)):
                notice_id = opp.get("noticeId", "")
                if notice_id in seen:
                    continue
                seen.add(notice_id)
                fields = _to_fields(opp)
                console.print(
                    f"  {fields['NoticeId']} | {fields['PostedDate']} | {fields['Title'][:70]}"
                )
                total += 1
    console.print(f"\n[green]{total} total results[/green]")


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


# ---------------------------------------------------------------------------
# SharePoint discovery helpers
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("hostname")
@click.argument("site_path")
@click.option("--env", "env_file", type=click.Path(path_type=Path), default=DEFAULT_ENV_FILE)
def get_site_id(hostname: str, site_path: str, env_file: Path):
    """
    Look up the Graph site ID for a SharePoint site.

    \b
    HOSTNAME   e.g. contoso.sharepoint.com
    SITE_PATH  e.g. /sites/MySite
    """
    try:
        cfg = SharePointConfig.from_env(env_file)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    client = GraphClient(cfg.tenant_id, cfg.client_id, cfg.client_secret)
    site_id = client.get_site_id(hostname, site_path)
    console.print(f"SP_SITE_ID=[green]{site_id}[/green]")


@cli.command()
@click.option("--env", "env_file", type=click.Path(path_type=Path), default=DEFAULT_ENV_FILE)
def list_lists(env_file: Path):
    """List all SharePoint lists on the configured site."""
    try:
        cfg = SharePointConfig.from_env(env_file)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    client = GraphClient(cfg.tenant_id, cfg.client_id, cfg.client_secret)
    lists = client.list_lists(cfg.site_id)

    table = Table(title="SharePoint Lists")
    table.add_column("Display Name", style="cyan")
    table.add_column("ID", style="dim")
    for lst in lists:
        table.add_row(lst.get("displayName", ""), lst.get("id", ""))
    console.print(table)
