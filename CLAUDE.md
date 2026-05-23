# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode (creates the `samgov-sync` CLI command)
pip install -e .

# Sync all profiles (destination and settings come from config.toml)
samgov-sync
```

No test suite or linter is configured yet.

## Architecture

```
src/samgov_sync/
  config.py              AppConfig, SamConfig, SharePointConfig, DiscordConfig, OllamaConfig
                         (load_toml reads config.toml; secrets come from .env)
                         SearchProfile dataclass + load_profiles(data: dict[str, Any])
  sam_client.py          SAM.gov SGS full-text search + official API for individual lookups;
                         _get() handles 429 Retry-After (seconds or HTTP date) — prints
                         resume time and exits rather than waiting indefinitely
  graph_client.py        Microsoft Graph API — SharePoint CRUD + site/list discovery
  pipeline.py            Pipeline: owns enrichment and dispatch.
                         run_profiles([(profile, writers)]) — per-profile writer routing.
                         _sync_profile → _search_and_dispatch + _monitor_and_dispatch
                         _enrich → _apply_full_description + _apply_summary
                         _dispatch → calls handle() on each writer, logs once per item
  ollama_client.py       summarize(host, model, fields) — returns {summary, deliverables}
  posters/
    base.py              Writer ABC + SyncStats + fingerprint() + is_closed() + _parse_deadline()
                         handle() returns (action, detail) tuple; never prints
    file.py              FileWriter — persists state/opps/<id>.json; always in every profile's
                         writer list; read by pipeline._load_cached_opp() before dispatch
    sharepoint.py        SharePointWriter — writes to a SharePoint list via Graph API
    discord.py           DiscordWriter — posts embeds to a Forum channel; tracks thread/message
                         IDs in state/.discord_state_<channel_id>.json
                         _WriteQueue — single background thread serialising all Discord API calls
  cli.py                 Plain `def cli()`. Steps: _load_config → _load_credentials →
                         _select_profiles → _startup_check → _assemble_profile_writers →
                         _run_pipeline → _print_stats
                         Startup check validates each service; failed writers set to None
                         and excluded from all profiles before the run starts.
```

**Data flow:**
`cli.py` loads config → startup check (validates + disables failed writers) → builds `(profile, [FileWriter, ...DestWriters])` pairs → `Pipeline.run_profiles()` loads all unique writers → for each profile: streams SAM.gov results, enriches serially, dispatches to that profile's writers → flushes all writers → prints stats.

**Enrichment (Pipeline, serial per item):**
1. `_to_fields()` maps raw SAM.gov result to normalized field names
2. `_load_cached_opp()` reads `state/opps/<id>.json` — single read, used for both checks below
3. `_apply_full_description()`: if `DescriptionFull` cached → skip API call; else call `fetch_description`
4. `_apply_summary()`: if `Summary` cached → skip Ollama; else run `ollama_summarize`
5. Dispatch fully-enriched record to all writers for this profile
6. Monitor phase: collect `active_ids()` from writers, re-fetch tracked items outside search window

**Destinations:**
Driven entirely by which IDs are configured per profile — no top-level `output` setting. A profile with both `discord_channel_id` and `sharepoint_list_id` writes to both. Comment out an ID to disable that destination.

**Discord threading:**
`DiscordWriter` uses `_WriteQueue` — one background thread serialising all Discord API calls. `handle()` enqueues tasks and returns immediately. `flush()` drains the queue.

**Closing logic:**
`is_closed(fields)` returns True if `Active != YES` or `ResponseDeadline` is past. `set_closed()` called on each writer: Discord posts closing notice + ❌ reaction; SharePoint sets `Active = "No"`.

**Adding a new destination:** subclass `Writer` from `posters/base.py`, implement `_load_existing`, `_create`, `_update`, `set_closed`, register in `posters/__init__.py`, add a branch in `cli._dest_writers_for_profile()`.

**Dedup key:** `NoticeId`. Change detection uses MD5 fingerprint of all mapped fields. `_existing` is populated at `load()` time and updated in-memory on each create, so cross-profile duplicates are caught correctly.

**Field mapping** lives in `pipeline._FIELD_MAP` (normalized key → SAM.gov JSON key). SGS results omit `naicsCode` and `typeOfSetAsideDescription`; `fetch_by_id` (official API) returns all fields.

**Multiple queries per profile:** `SearchProfile.queries` is a list; all queries run against the same destination, deduped by noticeId within a profile. Use `query = "foo"` (single) or `queries = ["foo", "bar"]` (multiple) in `config.toml`.

**Shared channels:** Multiple profiles can share the same `discord_channel_id` — they share the same state file and dedup correctly.

## Config files

- `config.toml` — all non-secret config (gitignored); create with `[app]`, `[discord]`, `[ollama]` sections and `[[search]]` entries
- `.env` — secrets only (gitignored): `SAM_API_KEY`, `DISCORD_BOT_TOKEN`, SP credentials
- `state/` — auto-created; holds `state/opps/<id>.json` and per-channel Discord state files (gitignored)
- Python 3.9–3.10 requires the `tomli` backport; 3.11+ uses stdlib `tomllib`

### config.toml format

```toml
[app]
# profile = "my-profile"   # optional: run only this named profile

[discord]
# state_file = "state/.discord_state.json"   # default shown

[ollama]
host = "http://machine3.local:11434"
model = "gemma4"        

[[search]]
name               = "gis"           # used with app.profile
query              = "gis"           # single search term
days_back          = 90
discord_channel_id = "123456789"

[[search]]
name               = "km"
queries            = ["knowledge management", "KM"]  # multiple terms, same channel, deduped
days_back          = 90
q_mode             = "EXACT"         # ALL | ANY | EXACT (default EXACT)

ptype              = "o"             # notice type:
# o=Solicitation, k=Combined, r=Sources Sought, p=Pre-Solicitation, a=Award, s=Special, g=Surplus, i=Bundle

# write to (whichever exist, all optional)
discord_channel_id = "987654321"
sharepoint_list_id = "abc123"
```

All `[[search]]` fields except `name` and `query`/`queries` are optional. `posted_from`/`posted_to` (MM/DD/YYYY) can be used instead of `days_back`.
