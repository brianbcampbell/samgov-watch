# Discord Setup

Each SAM.gov opportunity is posted as its own thread in a Discord **Forum channel**. The thread contains a structured embed (type, dates, agency, link) and the opportunity description. When an opportunity closes on SAM.gov the bot posts a closing notice and marks the thread. Team members can archive threads manually when discussion is done.

---

## Part 1 — Create a Discord application and bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. Give it a name (e.g. `SAM Watch`) → **Create**
3. Click **Bot** in the left sidebar
4. Click **Reset Token**, confirm, and copy the token
5. Paste after `DISCORD_BOT_TOKEN=` in `.env`
6. Under **Installation** → set **Install Link** to **None** and save
7. Uncheck **Public Bot** under Bot settings if checked → save

---

## Part 2 — Invite the bot to your server

1. Click **OAuth2** → **URL Generator** in the left sidebar
2. Under **Scopes** check `bot`
3. Under **Bot Permissions** check:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Embed Links
   - Read Message History
   - Add Reactions
4. Copy the generated URL, open it in a browser, and select your server

---

## Part 3 — Create a Forum channel and get its ID

1. In your Discord server, create a new channel → set type to **Forum**
2. Name it whatever you like (e.g. `#sam-gis`)
3. Enable **Developer Mode**: User Settings → Advanced → Developer Mode on
4. Right-click the channel → **Copy Channel ID**

---

## Part 4 — Configure

In `config.toml`:

```toml
[[search]]
name               = "gis"
url                = "https://sam.gov/search/?..."
days_back          = 90
discord_channel_id = "123456789012345678"
```

Multiple profiles can share the same `discord_channel_id` — they dedup correctly into the same channel.

---

## How threads work

| Event | What the bot does |
|---|---|
| New opportunity | Creates a forum thread with embed + description |
| Data changed | Edits the embed and updates description |
| No change | Skipped silently |
| Closed on SAM.gov | Posts closing notice + ❌ reaction |
| Reopened on SAM.gov | Removes closing notice and reaction |
| Done discussing | You archive the thread manually |

The bot never deletes threads. Archiving hides them from the active list but keeps history.

State is stored in `state/.discord_state_{channel_id}.json`. Don't delete these files unless you want everything re-posted.
