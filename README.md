# samgov-sync

**samgov-sync** monitors SAM.gov for government contracting opportunities relevant to a company's focus areas and automatically publishes them to collaboration destinations (Discord forum channels, SharePoint lists) where the team can discuss, track, and respond to them.

Configured search profiles define keyword queries and date windows. On each run the app fetches matching opportunities, enriches them with full descriptions and AI-generated summaries (via a local Ollama LLM), and syncs them to the configured destinations — creating new entries, updating changed ones, and closing items that fall out of scope. State is persisted locally so runs are idempotent and dedup is maintained across sessions.

**Skills demonstrated:** Python, SAM.gov REST API, Discord Bot API, Microsoft Graph API (SharePoint), local LLM integration (Ollama), background threading, incremental sync with fingerprint-based change detection, TOML/dotenv configuration, CLI tooling.

## Requirements

- Python 3.9+
- A [SAM.gov API key](https://sam.gov/profile/details) (free, requires account)
- **SharePoint:** An Azure AD app registration with `Sites.ReadWrite.All` (or `Sites.Selected`) application permission
- **Discord:** A webhook URL (Server Settings → Integrations → Webhooks)

## Install

```bash
pip install -e .
```

Or in an isolated environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

## Configure

### 1. Credentials

```bash
cp .env.example .env
```

Edit `.env` with your SAM.gov API key and Azure AD / SharePoint details.

**Finding SP_SITE_ID and SP_LIST_ID** — after filling in the Azure credentials:

```bash
# Look up the Graph site ID
samgov-sync get-site-id contoso.sharepoint.com /sites/MySite

# List all lists on the site
samgov-sync list-lists
```

### 2. Search profiles

```bash
cp searches.example.toml searches.toml
```

Edit `searches.toml`. Each `[[searches]]` block defines a named profile. See `searches.example.toml` for all available filters (`naics_code`, `ptype`, `set_aside`, date ranges, etc.).

### 3. SharePoint list columns

Create a list in SharePoint with these columns (all **Single line of text** unless noted):

| Column name | Notes |
|---|---|
| `Title` | Built-in — opportunity title |
| `NoticeId` | Used as the dedup key |
| `SolicitationNumber` | |
| `Department` | |
| `OfficeAddress` | |
| `PostedDate` | |
| `ResponseDeadline` | |
| `SetAside` | |
| `NaicsCode` | |
| `OpportunityType` | |
| `Active` | |
| `UiLink` | |
| `Description` | **Multiple lines of text** |

## Usage

```bash
# Sync all profiles → SharePoint (default)
samgov-sync sync

# Sync to Discord instead
samgov-sync sync --output discord

# Run a single profile
samgov-sync sync --profile cybersecurity-sources-sought

# Preview results without writing anywhere
samgov-sync sync --dry-run

# Use non-default file paths
samgov-sync sync --searches /path/to/searches.toml --env /path/to/.env
```

## How dedup works

Each opportunity is keyed on its SAM.gov `noticeId`. On each run:

- **New** → created (SharePoint: new list item; Discord: new embed posted to channel)
- **Unchanged** → skipped
- **Changed** → updated (SharePoint: item patched; Discord: original message edited)

Change detection uses an MD5 fingerprint of the mapped field values. The Discord poster persists message IDs and fingerprints in `.discord_state.json` so dedup survives across runs.

## Azure AD setup (quick reference)

1. **App registrations** → New registration
2. **API permissions** → Add → Microsoft Graph → Application → `Sites.ReadWrite.All` → Grant admin consent
3. **Certificates & secrets** → New client secret → copy value to `.env`
4. Copy the **Application (client) ID** and **Directory (tenant) ID** to `.env`
