# samgov-sync — App Flow

## Overview

```
config.toml + .env
      │
      ▼
   cli.py
      │  load config, credentials, profiles
      │  startup check (SAM.gov key, Ollama, Discord, SharePoint)
      │  disable any writer whose connection check failed
      │  build (profile → [FileWriter, DestWriter, ...]) pairs
      ▼
  Pipeline.run_profiles()
      │
      ├─ load()  ← all unique writers read their existing state
      │
      ├─ for each profile:
      │     ├─ search SAM.gov (SGS, streaming, paginated)
      │     │     for each result → _enrich() → _dispatch()
      │     │
      │     └─ monitor phase: re-fetch tracked IDs outside search window
      │           for each → _enrich() → _dispatch()
      │
      └─ flush() ← all writers drain queues / finalize
```

## Enrichment (serial, per item)

```
raw SGS result
      │
      ▼
 _to_fields()          map SAM.gov keys → normalized field names
      │
      ▼
 _load_cached_opp()    read state/opps/<id>.json  (None if not yet saved)
      │
      ├─ DescriptionFull in cache?
      │     yes → use cached Description, skip API call
      │     no  → fetch_description() → SAM.gov API (rate-limit aware)
      │             on success: set Description + DescriptionFull=true
      │
      └─ Summary in cache?
            yes → use cached Summary + Deliverables, skip Ollama
            no  → ollama_summarize() if host configured
                    on success: set Summary + Deliverables
      │
      ▼
 fully-enriched fields dict
```

## Dispatch (per item, per profile's writers)

```
_dispatch(fields, writers)
      │
      ├─ call handle(fields) on each writer
      │     Writer.handle():
      │       fingerprint(fields) vs stored fingerprint
      │         not in existing  → _create()  → return ("created", "")
      │         fingerprint diff → _update()  → return ("updated", "")
      │         same fingerprint → skip       → return ("skipped", "")
      │         exception        →            → return ("error",   msg)
      │
      └─ log once per item:
            any "created"  →  [+] <id>: <title>
            any "updated"  →  [~] <id>: updated
            all "skipped"  →  (silent)
            then one line per writer: ok / failed — <detail>
```

## Writers

| Writer | Persistence | Queue | set_closed() |
|---|---|---|---|
| `FileWriter` | `state/opps/<id>.json` | none (sync) | no-op |
| `DiscordWriter` | `state/.discord_state_<channel>.json` | `_WriteQueue` (1 bg thread) | closing notice + ❌ reaction |
| `SharePointWriter` | SharePoint list (live query at load) | none (sync) | sets `Active = "No"` |

## Caching / dedup

| What | Key | Stored in | Effect |
|---|---|---|---|
| Change detection | `fingerprint(fields)` MD5 | writer's `_existing` map | skip unchanged items |
| Full description | `DescriptionFull: true` flag | `state/opps/<id>.json` | skip `fetch_description` API call |
| Ollama summary | `Summary` field | `state/opps/<id>.json` | skip Ollama inference |

## SAM.gov rate limiting

`_get()` in `sam_client.py` handles 429 on the official API (`api.sam.gov`):
- Parses `Retry-After` as seconds or HTTP date
- Prints `SAM.gov rate limited — come back at HH:MM` and exits

The SGS search endpoint (`sam.gov/api/prod/sgs/...`) is unauthenticated and has no observed quota.

## State files

```
state/
  .discord_state_<channel_id>.json   thread/message IDs, fingerprints, active flags per notice
  opps/
    <noticeId>.json                  all mapped fields + Description + DescriptionFull flag
                                     + Summary + Deliverables (once fetched/summarized)
```
