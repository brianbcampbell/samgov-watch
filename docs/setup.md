# Setup Guide

This guide is for non-technical users setting up samgov-watch for the first time.

This is a lengthy and complex process but necessary because:
- This app is written in the Python language, and needs the Python runtime installed.
- Sharepoint and Discord require complicated authentication before allowing the app to post there



## Step 1 — Download the project

1. Go to [github.com/brianbcampbell/samgov-watch](https://github.com/brianbcampbell/samgov-watch)
2. Click the green **Code** button → **Download ZIP**
3. Extract the ZIP and move the folder somewhere easy to find, like:
   - Windows: `C:\Users\YourName\projects\samgov-watch\`
   - Mac: `~/projects/samgov-watch/`



## Step 2 — Install Python
This app is written in the Python language, and needs the Python runtime installed.
1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest version
2. Run the installer — on Windows, **check "Add Python to PATH"** before clicking Install



## Step 3 — Open a terminal in the project folder

**Windows:** Click Start → type `cmd` → Enter, then:
```
cd C:\Users\YourName\projects\samgov-watch
```

**Mac:** Cmd+Space → Terminal → Enter, then:
```
cd ~/projects/samgov-watch
```

**Both:** ensure Python install worked. 
```
python --version
```


## Step 4 — Install the app

```
pip install -e .
```

Wait for it to finish. You only need to do this once.

> If `pip` is not recognized, try `pip3 install -e .`


## Step 5 — Create your secrets file
⚠ **Never share your `.env` file.** It contains passwords and API keys. Anyone you share the app with needs to create their own.  

Secrets are the keys this app will use to get into your SAM, Discord, and SharePoint accounts. We store them in a file called .env which we will create by copying the example file.  
In your terminal:
```cmd
copy .env.example .env
```

(Mac: `cp .env.example .env`)

Open `.env` in a text editor (Windows: `notepad .env` / Mac: `open -e .env`) and fill in your credentials. See the destination-specific setup docs for where to find each value:

- [SharePoint setup](sharepoint.md)
- [Discord setup](discord.md)




## Step 6 — Build your search URL

The app searches SAM.gov using a URL copied directly from the website.

1. Go to [sam.gov/search](https://sam.gov/search)
2. Enter keywords and set filters until the results look right
3. Copy the URL from your browser's address bar (you'll paste it in step 7)

You can also use the **Search Editor** tab for Boolean queries like `"knowledge management" AND NOT "award"`.

**To test a search URL in this app before syncing anywhere:** add `query_only = true` to the `[app]` section of `config.toml`. Results are saved to `state/query/` as JSON — no credentials needed.

---

## Step 7 — Create config.toml

Create `config.toml` in the project folder:

```toml
[app]
# query_only = true   # uncomment to test queries without posting anywhere

[ollama]
# Uncomment and fill in if you have a local Ollama server for AI summaries
# host = "http://localhost:11434"
# model = "gemma3"

[[search]]
name               = "my search"
url                = "https://sam.gov/search/?..."   # paste your URL here
days_back          = 90
sharepoint_list_id = "your-list-id-here"
```

Add as many `[[search]]` blocks as you want — each runs independently and can write to a different list.

---

## Step 8 — Run it

```
samgov-sync
```

The app searches SAM.gov, enriches results, and syncs to your configured destinations. Re-run anytime — unchanged items are skipped automatically.
