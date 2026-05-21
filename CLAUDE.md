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
                         SearchProfile dataclass + load_profiles(data: dict)
  sam_client.py          SAM.gov SGS full-text search + official API for individual lookups;
                         all requests via _get() which handles 429 Retry-After (seconds or HTTP date)
  graph_client.py        Microsoft Graph API — SharePoint CRUD + site/list discovery
  pipeline.py            Pipeline: owns enrichment (fetch_description + Ollama) and dispatch.
                         run_profiles([(profile, writers)]) — per-profile writer routing.
                         _to_fields() field mapping, _clean_description(), _load_cached_summary().
  ollama_client.py       summarize(host, model, fields) — returns {summary, deliverables}
  posters/
    base.py              Writer ABC + SyncStats + fingerprint() + is_closed() + _parse_deadline()
    file.py              FileWriter — persists state/opps/<id>.json; always registered by cli
    sharepoint.py        SharePointWriter — writes to a SharePoint list via Graph API
    discord.py           DiscordWriter — posts embeds to a Forum channel; tracks thread/message
                         IDs in state/.discord_state_<channel_id>.json
                         _WriteQueue — single background thread serialising all Discord API calls
  cli.py                 Plain `def cli()` (no Click). Loads config, builds (profile, writers)
                         pairs, creates Pipeline, calls run_profiles(), prints stats table.
```

**Data flow:**
`cli.py` loads config → builds `(profile, [FileWriter, DestWriter])` pairs → `Pipeline.run_profiles()` calls `load()` on all unique writers → for each profile: streams SAM.gov results, enriches serially (fetch_description → Ollama), dispatches fully-enriched records to that profile's writers → `flush()` on all writers → aggregate and print stats.

**Enrichment (Pipeline, serial):**
1. Stream search results from SAM.gov (SGS, no key needed)
2. Fetch full description from official API (`fetch_description`) — serial, rate-limit safe
3. Run Ollama summarization if configured; reuse cached summary from `state/opps/<id>.json` if present
4. Dispatch fully-enriched record to all writers for this profile
5. Monitor phase: collect `active_ids()` from writers, re-fetch any tracked items not seen in search window

**Discord threading:**
`DiscordWriter` uses a `_WriteQueue` — one background thread that serialises all Discord API calls. `handle()` enqueues tasks and returns immediately. `flush()` calls `drain()` (blocks until queue empty).

**Closing logic:**
`is_closed(fields)` returns True if `Active != YES` or `ResponseDeadline` is in the past. When closed, `set_closed()` is called on each writer: Discord posts a closing notice + ❌ reaction; SharePoint sets `Active = "No"`.

**Adding a new destination:** subclass `Writer` from `posters/base.py`, implement `_load_existing`, `_create`, `_update`, `set_closed`, register in `posters/__init__.py`, add a branch in `cli._build_dest_writer()`.

**Dedup key:** `NoticeId`. Change detection uses MD5 of all mapped fields. `SharePointWriter` queries the live list; `DiscordWriter` reads its state JSON file.

**Field mapping** lives in `pipeline._FIELD_MAP` (normalized key → SAM.gov JSON key). SGS results omit `naicsCode` and `typeOfSetAsideDescription`; `fetch_by_id` (official API) returns all fields.

**Multiple queries per profile:** `SearchProfile.queries` is a list; all queries run against the same destination, deduped by noticeId. Use `query = "foo"` (single) or `queries = ["foo", "bar"]` (multiple) in `config.toml`.

**Shared channels:** Multiple profiles can share the same `discord_channel_id` — they share the same state file and dedup correctly.

## Config files

- `config.toml` — all non-secret config (gitignored); create with `[app]`, `[discord]`, `[ollama]` sections and `[[searches]]` entries
- `.env` — secrets only (gitignored): `SAM_API_KEY`, `DISCORD_BOT_TOKEN`, SP credentials
- `state/` — auto-created; holds `state/opps/<id>.json` and per-channel Discord state files (gitignored)
- Python 3.9–3.10 requires the `tomli` backport; 3.11+ uses stdlib `tomllib`

Profiles without a channel ID for the active output are silently skipped.

### config.toml format

```toml
[app]
# profile = "my-profile"   # optional: run only this named profile

[discord]
# state_file = "state/.discord_state.json"   # default shown

[ollama]
host = "http://machine3.local:11434"
# model = "gemma4"                           # default shown

[[searches]]
name               = "gis"           # used with app.profile
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

All `[[searches]]` fields except `name` and `query`/`queries` are optional. `posted_from`/`posted_to` (MM/DD/YYYY) can be used instead of `days_back`.
