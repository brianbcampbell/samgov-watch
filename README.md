# samgov-watch

**samgov-watch** monitors SAM.gov for government contracting opportunities relevant to a company's focus areas and automatically publishes them to collaboration destinations (Discord forum channels, SharePoint lists) where the team can discuss, track, and respond to them.

Configured search profiles define keyword queries and date windows. On each run the app fetches matching opportunities, enriches them with full descriptions and AI-generated summaries (via a local Ollama LLM), and syncs them to the configured destinations — creating new entries, updating changed ones, and closing items that fall out of scope. State is persisted locally so runs are idempotent and dedup is maintained across sessions.

**Skills demonstrated:** Python, SAM.gov REST API, Discord Bot API, Microsoft Graph API (SharePoint), local LLM integration (Ollama), background threading, incremental sync with fingerprint-based change detection, TOML/dotenv configuration, CLI tooling.

---

## ⚠ Notice

- **Use at your own risk.** This project comes with no warranty of any kind.
- This is an early, in-progress effort — not complete, not fully tested, not polished.
- **Discord** is working and has been tested by the author.
- **SharePoint** support is implemented but has not been used or tested yet. Expect rough edges.
- Running this app will post messages to your Discord server and/or write to your SharePoint list. Review your configuration carefully before running it.

---

## Setup

### Step 1 — Download the project

1. Go to [github.com/brianbcampbell/samgov-watch](https://github.com/brianbcampbell/samgov-watch) if you're not already there.
2. Click the green **Code** button, then click **Download ZIP**
3. Once downloaded, right-click the ZIP file and choose **Extract All** (Windows) or double-click it (Mac)
4. Move the extracted folder somewhere easy to find, like `C:\Users\YourName\projects\samgov-watch\` on Windows or `~/projects/samgov-watch/` on Mac

### Step 2 — Install Python

Python is the programming language this app runs on. You only need to install it once.

1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest version
2. Run the installer — on Windows, **check the box that says "Add Python to PATH"** before clicking Install
3. To confirm it worked: open a terminal (see next step) and type `python --version` — you should see something like `Python 3.12.0`

### Step 3 — Open a terminal and navigate to the project folder

A terminal is a text window where you type commands to control your computer.

**Windows:**
1. Click **Start**, type `cmd`, press **Enter** — a black window opens
2. Type the following, replacing the path with wherever you put the folder:
```
cd C:\Users\YourName\projects\samgov-watch
```
Press **Enter**.

**Mac:**
1. Press **Cmd + Space**, type `Terminal`, press **Enter**
2. Type the following, replacing the path with wherever you put the folder:
```
cd ~/projects/samgov-watch
```
Press **Enter**.

> After typing a `cd` command you won't see any confirmation — that's normal. You're now "inside" the project folder and commands you type will run there.

### Step 4 — Install the app

In the terminal, type:

```
pip install -e .
```

Press **Enter** and wait. You'll see a lot of text scroll by as it downloads the required libraries. When it finishes and you see the prompt again, it's done. You only need to do this once.

> If you see an error saying `pip` is not recognized, try `pip3 install -e .` instead.

### Step 5 — Create your secrets file

This app needs to log in to SAM.gov, Discord, and/or SharePoint on your behalf. You store those credentials in a file called `.env` that lives in the project folder. This file is only used by this app on your computer — never share it or send it to anyone.

In your terminal, type:

```
copy .env.example .env
```

(On Mac, type `cp .env.example .env` instead.)

Now open the `.env` file in a text editor. On Windows you can type `notepad .env` in the terminal. On Mac, type `open -e .env`.

You'll see something like this:

```
SAM_API_KEY=your_sam_gov_api_key_here
DISCORD_BOT_TOKEN=your-bot-token-here
SP_TENANT_ID=your-tenant-id
...
```

Replace each placeholder value with your actual key or token. See **Getting your credentials** below for where to find each one. Leave any lines blank if you're not using that destination (e.g., leave the SharePoint lines alone if you're only using Discord).

> **If you share this app with someone else:** do NOT give them your `.env` file. It contains your passwords and API keys. They need to create their own `.env` file with their own credentials.

### Step 6 — Create your config file

Create a new file called `config.toml` in the project folder. Open Notepad (Windows) or TextEdit (Mac), paste in the following as a starting point, and save it as `config.toml` in the project folder:

```toml
[app]

[ollama]
# Remove the # below and fill in your Ollama server address if you want AI summaries
# host = "http://localhost:11434"
# model = "gemma3"

[[searches]]
name               = "my search"
query              = "your keywords here"
days_back          = 90
discord_channel_id = "your_channel_id_here"
```

Change `query` to the keywords you want to search for on SAM.gov. Change `discord_channel_id` to your Discord channel ID (see below for how to find it). You can add as many `[[searches]]` blocks as you want — each one runs a separate search and can post to a different channel.

### Step 7 — Run it

In your terminal, type:

```
samgov-sync
```

Press **Enter**. The app will connect to SAM.gov, find matching opportunities, and post them to your configured Discord channel or SharePoint list. Run it again anytime — opportunities that haven't changed since the last run will be skipped automatically.

---1

## Getting your credentials

### SAM.gov API key

1. Create a free account at [sam.gov](https://sam.gov)
2. After logging in, click your name in the top right → **Profile**
3. Look for the **API Keys** section and click **Request an API Key**
4. It will be emailed to you within a few minutes
5. Open your `.env` file and paste it after `SAM_API_KEY=`

### Discord bot token and channel ID

A Discord "bot" is an automated account your app uses to post messages. You create one for free.

**Create the bot:**
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and log in with your Discord account
2. Click **New Application**, give it a name (e.g., "SAM Watch"), click **Create**
3. Click **Bot** in the left menu
4. Click **Reset Token**, confirm, then copy the token that appears
5. Open your `.env` file and paste the token after `DISCORD_BOT_TOKEN=`

**Invite the bot to your server:**
1. Still in the Developer Portal, click **OAuth2** → **URL Generator** in the left menu
2. Under **Scopes**, check `bot`
3. Under **Bot Permissions**, check: `Send Messages`, `Create Public Threads`, `Send Messages in Threads`, `Embed Links`, `Read Message History`, `Add Reactions`
4. Copy the URL at the bottom, paste it in your browser, and follow the prompts to add the bot to your server

**Get a channel ID:**
1. In Discord, open **User Settings** (gear icon) → **Advanced** → turn on **Developer Mode**
2. Right-click the channel you want to post to → **Copy Channel ID**
3. Paste that number into your `config.toml` as the `discord_channel_id`

### SharePoint credentials

SharePoint requires setting up an "app registration" in Microsoft Azure — this is how you give the app permission to write to your SharePoint list without using your personal login.

1. Go to [portal.azure.com](https://portal.azure.com) and sign in with your Microsoft 365 account
2. In the search bar at the top, type **App registrations** and click it
3. Click **New registration** → give it a name → click **Register**
4. On the overview page, copy:
   - **Application (client) ID** → paste after `SP_CLIENT_ID=` in `.env`
   - **Directory (tenant) ID** → paste after `SP_TENANT_ID=` in `.env`
5. Click **Certificates & secrets** (left menu) → **New client secret** → give it a description → **Add**
6. Copy the **Value** (not the ID) → paste after `SP_CLIENT_SECRET=` in `.env` — copy it now, you can't see it again after you leave the page
7. Click **API permissions** (left menu) → **Add a permission** → **Microsoft Graph** → **Application permissions** → search for `Sites.ReadWrite.All` → check it → **Add permissions**
8. Click **Grant admin consent for [your org]** and confirm — you need to be an admin to do this
9. To find your site ID: in your browser, go to `https://yourcompany.sharepoint.com/sites/YourSiteName/_api/site/id` — the value inside the quotes in the response is your site ID → paste after `SP_SITE_ID=` in `.env`

---

## How it works

On each run:

1. The app reads your search profiles from `config.toml`
2. It searches SAM.gov for matching opportunities
3. It fetches the full description for each result
4. If an Ollama AI server is configured, it generates a plain-English summary and list of deliverables
5. New opportunities are posted to Discord/SharePoint; changed ones are updated; opportunities that no longer appear in your search are marked closed
6. Everything is saved locally so the next run knows what's already been posted and won't post duplicates
