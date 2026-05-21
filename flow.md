# samgov-sync — App Flow

## Current implementation

```mermaid
flowchart LR
    subgraph Search["Search (serial, streaming)"]
        SGS["SAM.gov SGS<br/>paginated queries"]
        Monitor["Monitor<br/>fetch_by_id × N<br/>(ThreadPoolExecutor·8)"]
    end

    subgraph ItemPool["Item worker pool (DISCORD_WORKER_THREADS=8)"]
        W1["worker"]
        W2["worker"]
        W3["worker"]
        Wn["…"]
    end

    subgraph OllamaQ["Ollama queue (1 worker)<br/>skips items with valid _ext.json"]
        OQ["queue.Queue"]
        OW["call Ollama<br/>write _ext.json"]
    end

    subgraph DiscordQ["Discord write queue (1 worker, lifetime of poster)"]
        DQ["queue.Queue"]
        DW["Writer thread<br/>serial · rate-limit aware<br/>holds _state_lock for mutations"]
    end

    Drain1(["ollama_queue.drain()"])
    Drain2(["write_queue.drain()"])

    SGS & Monitor -->|stream items| ItemPool

    W1 & W2 & W3 & Wn -->|"enrich · fingerprint · save_opp"| W1
    W1 & W2 & W3 & Wn -->|"① create/update task"| DQ
    W1 & W2 & W3 & Wn -->|"② ollama task (if host set)"| OQ

    OW -->|"③ summary write task"| DQ
    DQ --> DW -->|Discord API| DiscordAPI[("Discord")]

    ItemPool --> Drain1 --> Drain2
```

**Ordering guarantee.** Each item enqueues its Discord create/update task **①** before its Ollama task **②**. Ollama only enqueues the summary write **③** after inference completes. Since the Discord write queue is FIFO and serial, create/update always executes before summary for the same item — no explicit drain barrier needed between them.

**Drain order.** After the item pool:
1. `ollama_queue.drain()` — all pending inference runs; summary write tasks land on Discord queue.
2. `write_queue.drain()` — all remaining Discord API calls (creates, updates, summaries) complete.

## Concurrency summary

| Stage | Workers | Bottleneck |
|---|---|---|
| Search | 1 (serial) | SAM.gov pagination |
| Monitor fetch_by_id | 8 | SAM.gov API I/O |
| Item enrichment | 8 (`DISCORD_WORKER_THREADS`) | SAM.gov API I/O |
| Ollama inference | 1 | GPU / local LLM |
| Discord API writes | 1 | Discord rate limits |

## State files

```
state/
  .discord_state_{channel_id}.json   # thread/message IDs, fingerprints, active flags
  opps/
    {noticeId}.json                  # raw mapped fields (written on create/update)
    {noticeId}_ext.json              # Ollama output: summary + deliverables
                                     # queue skips this item if summary key is not None
```
