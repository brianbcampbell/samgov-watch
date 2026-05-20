# Discord Integration Setup

Each SAM.gov opportunity is posted as its own thread in a Discord **Forum channel**. The thread title is the opportunity title. The first message contains the full details — description, dates, type, office, department — as a rich embed. When an opportunity closes on SAM.gov, the bot edits the embed to grey and posts a closing notice in the thread. Team members can then archive the thread manually when discussion is done.

---

## 1. Create a Discord Application and Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**.
2. Give it a name (e.g. `SAM Sync`) and click **Create**.
3. In the left sidebar click **Bot**.
4. Click **Reset Token**, confirm, and copy the token — you'll need it shortly.
5. Under **Privileged Gateway Intents**, no extra intents are needed. Leave them off.

---

## 2. Invite the Bot to Your Server

Discord automatically enables a "Default Authorization Link" on new apps. Private apps can't use it, which causes a save error. Disable it first, then generate a one-time invite URL manually.

1. In the left sidebar click **Installation**.
2. Find **Install Link** and change the dropdown to **None**. Save.
3. Also uncheck **Public Bot** under Bot settings if it's checked. Save.
4. In the left sidebar click **OAuth2** → **URL Generator**.
5. Under **Scopes** check `bot`.
6. Under **Bot Permissions** check:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Embed Links
7. Copy the generated URL at the bottom, open it in a browser, and select your server.

---

## 3. Enable Developer Mode

You need Developer Mode on to copy channel IDs.

1. Open Discord → **User Settings** (gear icon) → **Advanced**.
2. Toggle **Developer Mode** on.

---

## 4. Create a Forum Channel

1. In your server, create a new channel and set its type to **Forum**.
2. Name it whatever you like (e.g. `#sam-gis-opportunities`).
3. Right-click the channel → **Copy Channel ID**.

---

## 5. Configure

Add to your `.env`:

```
DISCORD_BOT_TOKEN=your-bot-token-here
```

In `searches.toml`, set `discord_channel_id` per profile:

```toml
[[searches]]
name               = "gis"
query              = "gis"
days_back          = 90
discord_channel_id = "123456789012345678"
```

Multiple profiles can share a `discord_channel_id` — they'll dedup correctly into the same channel. A single profile can also search multiple terms into one channel:

```toml
[[searches]]
name               = "gis-all"
queries            = ["gis", "geospatial", "geographic information"]
days_back          = 90
discord_channel_id = "123456789012345678"
```

---

## 6. Run

```bash
samgov-sync sync --output discord
```

To preview without posting:

```bash
samgov-sync sync --output discord --dry-run
```

---

## How threads work

| Event | What the bot does |
|---|---|
| New active opportunity | Creates a forum thread; starter message = full embed (blue) |
| Opportunity data changed | Edits the starter message in-place (gold) |
| No change since last run | Skipped silently |
| Opportunity closed on SAM.gov | Edits embed to grey + posts a closing notice in the thread |
| Done discussing | **You** archive the thread manually in Discord |

The bot never deletes threads. Archiving hides them from the active list but keeps history.

---

## State files

State is saved in `state/` (gitignored), one file per channel: `state/.discord_state_{channel_id}.json`. It maps each SAM.gov notice ID to its Discord thread and message IDs so dedup and updates work across runs. Don't delete these unless you want everything re-posted.
