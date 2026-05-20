# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode (creates the `samgov-sync` CLI command)
pip install -e .

# Sync all profiles to Discord
samgov-sync sync --output discord

# Sync all profiles to SharePoint
samgov-sync sync --output sharepoint

# Run a single named profile
samgov-sync sync --profile <name>

# Dry run — print results, write nothing
samgov-sync sync --dry-run

# Discover SharePoint IDs
samgov-sync get-site-id <hostname> <site_path>
samgov-sync list-lists
```

No test suite or linter is configured yet.

## Architecture

```
src/samgov_sync/
  config.py              SamConfig, SharePointConfig, DiscordConfig (each loads its own env vars)
                         SearchProfile dataclass + load_profiles() (TOML)
  sam_client.py          SAM.gov SGS full-text search (no API key needed) + official API for
                         individual lookups by notice ID
  graph_client.py        Microsoft Graph API — SharePoint CRUD + site/list discovery
  sync.py                _to_fields() mapping + _clean_description() + run_sync()
  posters/
    base.py              Poster ABC + SyncStats + fingerprint()
    sharepoint.py        SharePointPoster — writes to a SharePoint list via Graph API
    discord.py           DiscordPoster — posts embeds to a Forum channel; tracks thread/message
                         IDs in state/ per channel
  cli.py                 Click CLI: sync, get-site-id, list-lists
```

**Data flow:**
`cli.py` loads `SamConfig` + builds a `Poster` → `run_sync()` iterates over all queries in the profile, streams results through `_to_fields()` (deduped by noticeId) → `poster.sync()` loads existing records, then creates/updates/skips each item.

**Adding a new destination:** subclass `Poster` from `posters/base.py`, implement `_load_existing`, `_create`, `_update`, register it in `posters/__init__.py`, add a branch in `cli._build_poster()`.

**Dedup key:** `NoticeId` (SAM.gov `noticeId` / SGS `_id`). Change detection uses MD5 of all mapped fields. `SharePointPoster` queries the live list; `DiscordPoster` reads `state/.discord_state_{channel_id}.json`.

**Field mapping** lives in `sync._FIELD_MAP` (normalized key → SAM.gov JSON key). SGS results do not include `naicsCode` or `typeOfSetAsideDescription` (those fields will be blank). `fetch_by_id` uses the official API and returns all fields.

**Multiple queries per profile:** `SearchProfile.queries` is a list; all queries run against the same destination and are deduped by noticeId before syncing. Use `query = "foo"` (single) or `queries = ["foo", "bar"]` (multiple) in `searches.toml`.

**Shared channels:** Multiple profiles can share the same `discord_channel_id` — they share the same state file and dedup correctly.

## Config files

- `.env` — credentials (gitignored); copy from `.env.example`. Only vars for the chosen `--output` are required.
- `searches.toml` — search profiles (gitignored); create it with `[[searches]]` entries (see format below)
- `state/` — auto-created; holds per-channel Discord state files (gitignored)
- Python 3.9–3.10 requires the `tomli` backport; 3.11+ uses stdlib `tomllib`

### searches.toml format

```toml
[[searches]]
name               = "gis"           # used with --profile flag
query              = "gis"           # single search term
days_back          = 90
discord_channel_id = "123456789"

[[searches]]
name               = "km"
queries            = ["knowledge management", "KM"]  # multiple terms, same channel, deduped
days_back          = 90
q_mode             = "EXACT"         # ALL | ANY | EXACT (default EXACT)
ptype              = "o"             # notice type: o=Solicitation, k=Combined, r=Sources Sought,
                                     # p=Pre-Solicitation, a=Award, s=Special, g=Surplus, i=Bundle
discord_channel_id = "987654321"
```

All fields except `name` and `query`/`queries` are optional. `posted_from`/`posted_to` (MM/DD/YYYY) can be used instead of `days_back`.
