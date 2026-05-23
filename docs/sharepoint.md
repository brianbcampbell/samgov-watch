# SharePoint Setup

SharePoint requires three things: an Azure app registration, a SharePoint list with the right columns, and the IDs for your site and list.

---

## Part 1 — Azure app registration

This gives the app permission to write to SharePoint. You need to be a Microsoft 365 admin.

1. Go to [portal.azure.com](https://portal.azure.com) and sign in
2. Search for **App registrations** → **New registration** → give it a name (e.g. "SAM Watch") → **Register**
3. On the overview page, copy:
   - **Application (client) ID** → paste after `SP_CLIENT_ID=` in `.env`
   - **Directory (tenant) ID** → paste after `SP_TENANT_ID=` in `.env`
4. **Certificates & secrets** (left menu) → **New client secret** → **Add**
5. Copy the **Value** immediately → paste after `SP_CLIENT_SECRET=` in `.env`
   > You can only see this value once. If you navigate away first, delete it and create a new one.
6. **API permissions** (left menu) → **Add a permission** → **Microsoft Graph** → **Application permissions** → search `Sites.Manage.All` → check it → **Add permissions**
7. Click **Grant admin consent for [your org]** and confirm

---

## Part 2 — Create the SharePoint list

1. Go to your SharePoint site → **New → List** → **Blank list**
2. Name it (e.g. `SAM Opportunities`) → **Create**
3. Add the following columns via **+ Add column**:

| Column name | Type |
|---|---|
| NoticeId | Single line of text |
| SolicitationNumber | Single line of text |
| Department | Single line of text |
| OfficeAddress | Single line of text |
| PostedDate | Single line of text |
| ResponseDeadline | Single line of text |
| SetAside | Single line of text |
| NaicsCode | Single line of text |
| OpportunityType | Single line of text |
| Active | Single line of text |
| UiLink | Single line of text |
| Description | Multiple lines of text |
| Summary | Multiple lines of text |
| Deliverables | Multiple lines of text |

> **Column names must be entered exactly as shown** — no spaces, matching capitalisation. SharePoint sets the internal API name at creation time and it cannot be changed without breaking the integration.
>
> `Summary` and `Deliverables` are only written if an Ollama server is configured. You can skip them otherwise.

### Optional: add your own status column

You can add a **Choice** column (e.g. `Action` with choices like `New`, `Reviewing`, `Pursuing`, `Ignore`) for your team to track internal status. The app will never touch it — it only writes the columns listed above.

To hide ignored items: create a filtered view (**All Items** dropdown → **Create new view**) with the filter `Action is not equal to Ignore`.

---

## Part 3 — Find your Site ID and List ID

**Site ID:**

1. Go to [Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer) and sign in
2. Run this query (replace with your values):
   ```
   https://graph.microsoft.com/v1.0/sites/yourcompany.sharepoint.com:/sites/YourSiteName
   ```
3. Copy the `"id"` value from the response — it looks like:
   ```
   yourcompany.sharepoint.com,xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx,yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
   ```
4. Paste after `SP_SITE_ID=` in `.env`

**List ID:**

1. Open the list → gear icon (⚙) → **List settings**
2. In the URL, find `List=%7B...%7D`
3. Copy the value between `%7B` and `%7D` — that is the list GUID
4. Paste after `sharepoint_list_id =` in `config.toml`:

```toml
[[search]]
name               = "my search"
url                = "https://sam.gov/search/?..."
days_back          = 90
sharepoint_list_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```
