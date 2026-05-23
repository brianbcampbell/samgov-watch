# samgov-watch

Searches SAM.gov for government contracting opportunities and syncs them to SharePoint lists (and optionally Discord forum channels). On each run it fetches matching opportunities, generates AI summaries via a local Ollama LLM, and syncs to configured destinations — creating new entries, updating changed ones, and closing items that fall out of scope. Runs are idempotent; state is persisted locally.

---

## ⚠ Notice

- Use at your own risk — no warranty.
- SharePoint is working. Discord is implemented but no longer actively used by the author.

---

## Quick start

```bash
pip install -e .
cp .env.example .env       # fill in credentials
# create config.toml (see below)
samgov-sync
```

## config.toml

```toml
[app]
# profile    = "gis"       # run only this named profile
# query_only = true        # test search results without syncing

[ollama]
host  = "http://localhost:11434"
model = "gemma3"

[[search]]
name               = "gis"
url                = "https://sam.gov/search/?..."   # paste URL from sam.gov/search
days_back          = 90
sharepoint_list_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
# discord_channel_id = "..."
```

`url` — copy directly from the SAM.gov search page after tuning your filters. The Search Editor tab supports Boolean queries.

Multiple `[[search]]` blocks run independently and can write to different destinations. Profiles with both IDs write to both.

## .env

```
SP_TENANT_ID=...
SP_CLIENT_ID=...
SP_CLIENT_SECRET=...
SP_SITE_ID=...

DISCORD_BOT_TOKEN=...   # only needed if using Discord
```

---

## Architecture

```
sam_client.py      SGS full-text search (no API key required)
pipeline.py        Fetch → enrich (Ollama) → dispatch to writers
ollama_client.py   summarize(host, model, fields) → {summary, deliverables}
posters/
  file.py          Persists state/opps/<id>.json — always runs
  sharepoint.py    Microsoft Graph API — creates/updates list items
  discord.py       Discord Bot API — creates/updates forum threads
graph_client.py    SharePoint CRUD via Microsoft Graph
config.py          Loads config.toml + .env
cli.py             Entry point
```

State lives in `state/` (gitignored): `state/opps/` for cached opportunity JSON, `state/.discord_state_<channel_id>.json` for Discord thread/message IDs.

---

## Detailed setup guides

- [General setup (non-technical)](docs/setup.md)
- [SharePoint setup](docs/sharepoint.md)
- [Discord setup](docs/discord.md)
