# llm-inference-logger

A lightweight, production-quality system for logging, storing, and inspecting
LLM inference calls — built around a thin SDK, a FastAPI ingestion service,
PostgreSQL persistence, and a Streamlit chatbot UI.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Your application  (or the Streamlit chatbot)                   │
│                                                                 │
│   from llm_logger import LLMLogger                              │
│   client = LLMLogger(ingestion_url=...).wrap_anthropic(client)  │
│                         │                                       │
│                         │  fire-and-forget HTTP POST            │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
          ┌───────────────────────────┐
          │  Ingestion Service        │
          │  FastAPI  · port 8000     │
          │                           │
          │  POST /logs               │
          │  GET  /logs               │
          │  GET  /conversations      │
          │  GET  /conversations/{id} │
          │  DELETE /conversations/id │
          └────────────┬──────────────┘
                       │  SQLAlchemy ORM
                       ▼
          ┌───────────────────────────┐
          │  PostgreSQL 15            │
          │  port 5432                │
          │                           │
          │  conversations            │
          │  messages                 │
          │  inference_logs           │
          └───────────────────────────┘

          ┌───────────────────────────┐
          │  Streamlit chatbot        │
          │  port 8501                │
          │                           │
          │  Multi-turn chat (Claude) │
          │  Conversation sidebar     │
          │  Per-message token stats  │
          └───────────────────────────┘
```

---

## Quick Start (Docker Compose)

```bash
# 1. Clone / enter the project
cd llm-inference-logger

# 2. Configure secrets
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 3. Build and start everything
docker-compose up --build

# Services:
#   Chatbot    → http://localhost:8501
#   API docs   → http://localhost:8000/docs
#   PostgreSQL → localhost:5432
```

---

## Manual Setup (no Docker)

### 1. PostgreSQL

Start a local PostgreSQL instance and create a database:

```sql
CREATE USER ollive WITH PASSWORD 'ollive';
CREATE DATABASE ollive_logs OWNER ollive;
```

### 2. Ingestion service

```bash
cd ingestion
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

export DATABASE_URL=postgresql://ollive:ollive@localhost:5432/ollive_logs
uvicorn app.main:app --reload --port 8000
```

### 3. SDK (optional, for use in your own code)

```bash
cd sdk
pip install -e .
```

### 4. Chatbot

```bash
cd chatbot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export INGESTION_URL=http://localhost:8000
streamlit run app.py
```

---

## SDK Usage

```python
import anthropic
from llm_logger import LLMLogger

# Create and wrap the client
raw_client = anthropic.Anthropic()
logger = LLMLogger(
    ingestion_url="http://localhost:8000",
    session_id="my-user-session",      # optional, auto-generated otherwise
    async_ship=True,                    # non-blocking (default)
    redact_pii=False,                   # set True to scrub emails/phones/SSNs
)
client = logger.wrap_anthropic(raw_client)

# All subsequent calls are transparently logged
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)

# OpenAI is also supported
import openai
oai_client = openai.OpenAI()
oai_client = logger.wrap_openai(oai_client)
response = oai_client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Conversation management

```python
# Start a fresh conversation (new UUID)
new_id = logger.new_conversation()

# Resume an existing one
logger.set_conversation_id("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
```

---

## API Reference

### POST /logs

Ingest a new inference log.  Conversation is auto-created if absent.

**Request body** (JSON):
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| conversation_id | string | yes | UUID of the conversation |
| session_id | string | yes | Caller session identifier |
| model | string | yes | e.g. `claude-sonnet-4-6` |
| provider | string | yes | `anthropic` or `openai` |
| latency_ms | int | no | Defaults to 0 |
| prompt_tokens | int | no | |
| completion_tokens | int | no | |
| total_tokens | int | no | |
| request_status | string | no | `success` (default) or `error` |
| error_message | string | no | |
| input_preview | string | no | First 255 chars of prompt |
| output_preview | string | no | First 255 chars of response |
| timestamp | ISO-8601 | no | Defaults to server time |

**Response**: `201 Created` + the stored log object.

---

### GET /logs

List logs with optional filters.

| Query param | Type | Notes |
|-------------|------|-------|
| page | int | Default 1 |
| page_size | int | Default 50, max 200 |
| provider | string | Filter by provider |
| model | string | Filter by model |
| status | string | `success` or `error` |
| conversation_id | string | Restrict to one conversation |

---

### GET /conversations

List conversations, newest first.

| Query param | Type | Notes |
|-------------|------|-------|
| page | int | Default 1 |
| page_size | int | Default 50, max 200 |
| session_id | string | Filter by session |

---

### GET /conversations/{id}

Full conversation: metadata + messages (sorted) + inference_logs (sorted).

---

### DELETE /conversations/{id}

Delete conversation and all its messages and logs. Returns `204 No Content`.

---

## Database Schema

```
conversations
  id            VARCHAR(36)  PK
  session_id    VARCHAR(255) NOT NULL  (indexed)
  title         VARCHAR(500)
  created_at    TIMESTAMPTZ
  updated_at    TIMESTAMPTZ

messages
  id              VARCHAR(36)  PK
  conversation_id VARCHAR(36)  FK → conversations.id  (cascade delete)
  role            VARCHAR(20)  -- "user" | "assistant"
  content         TEXT
  created_at      TIMESTAMPTZ

inference_logs
  id                VARCHAR(36)  PK
  conversation_id   VARCHAR(36)  FK → conversations.id  (cascade delete)
  message_id        VARCHAR(36)  FK → messages.id  (set null on delete)
  model             VARCHAR(128)
  provider          VARCHAR(64)
  latency_ms        INTEGER
  prompt_tokens     INTEGER
  completion_tokens INTEGER
  total_tokens      INTEGER
  request_status    VARCHAR(20)  -- "success" | "error"
  error_message     TEXT
  input_preview     VARCHAR(255)
  output_preview    VARCHAR(255)
  created_at        TIMESTAMPTZ
```

---

## Design Decisions

### String UUIDs instead of native UUID columns
SQLAlchemy's UUID type is fully supported on PostgreSQL, but using `VARCHAR(36)`
keeps the models portable across SQLite (for local testing) and PostgreSQL
without any dialect-specific handling.

### Fire-and-forget shipping with threading
The SDK ships logs in a daemon thread (`threading.Thread(daemon=True)`).
This means:
- The calling application is never blocked.
- If the process exits before the thread finishes, the log is silently dropped —
  an acceptable trade-off for a logging side-channel.
- Max 3 retries with exponential back-off (0.25 s, 0.5 s, 1 s) and a 2 s
  socket timeout per attempt.

### Conversation auto-creation on POST /logs
The SDK only knows its `conversation_id`; it should not need a separate
"create conversation" call.  The ingestion endpoint upserts the conversation
record transparently.

### PII redaction is opt-in
Redaction (`redact_pii=True`) replaces emails, phone numbers, and SSNs in
the short *previews* only.  Full message content is never stored by the
ingestion service — only the 200-char previews captured by the SDK.

---

## Trade-offs

| Decision | Upside | Downside |
|----------|--------|----------|
| SQLAlchemy `create_all` on startup | Zero-config first run | Not suitable for prod schema migrations — swap for Alembic |
| In-process threading for shipping | Simple, no extra infra | A killed process can lose the last few logs |
| Previews only (not full content) | Privacy-friendly by default | Can't replay or debug full prompts from the DB |
| Streamlit for the UI | Fast to build, easy to extend | Not suitable for high-concurrency or embedding in another app |

---

## What I'd Improve with More Time

1. **Alembic migrations** — replace `create_all` with a proper migration history.
2. **Streaming support** — intercept `messages.stream()` and accumulate tokens.
3. **Async ingestion service** — use `asyncpg` + SQLAlchemy async to handle burst traffic.
4. **Structured logging** — ship full (optionally encrypted) prompt/response blobs to
   object storage (S3/GCS) with the DB storing only metadata + a reference key.
5. **Metrics endpoint** — `/metrics` (Prometheus format) for latency histograms,
   token-cost tracking, error rates.
6. **Authentication** — API key middleware on the ingestion service.
7. **Batched shipping** — buffer logs for 100 ms and send in bulk to reduce HTTP overhead.
8. **OpenTelemetry integration** — emit traces alongside logs for distributed tracing.
