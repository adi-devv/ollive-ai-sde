# ollive-ai-sde — LLM Inference Logging System

A lightweight, production-quality system for logging, storing, and inspecting LLM inference calls — built around a thin Python SDK, a FastAPI ingestion service, SQLite/PostgreSQL persistence, and a Streamlit chatbot UI.

**Chatbot powered by:** Llama 3.3 70B via Groq API  
**SDK supports:** Any Groq / OpenAI-compatible provider + Anthropic

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit Chatbot  (or your own app)                           │
│                                                                 │
│   from llm_logger import LLMLogger                              │
│   client = LLMLogger(ingestion_url=...).wrap_openai(client)     │
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
          │  POST /messages           │
          │  GET  /logs               │
          │  GET  /conversations      │
          │  GET  /conversations/{id} │
          │  DELETE /conversations/id │
          └────────────┬──────────────┘
                       │  SQLAlchemy ORM
                       ▼
          ┌───────────────────────────┐
          │  SQLite (dev)             │
          │  PostgreSQL 15 (prod)     │
          │                           │
          │  conversations            │
          │  messages                 │
          │  inference_logs           │
          └───────────────────────────┘

          ┌───────────────────────────┐
          │  Streamlit chatbot        │
          │  port 8501                │
          │                           │
          │  Multi-turn chat (Groq)   │
          │  List conversations       │
          │  Resume conversation      │
          │  Cancel conversation      │
          │  Per-message token stats  │
          └───────────────────────────┘
```

---

## Quick Start (Docker Compose)

```bash
# 1. Clone / enter the project
cd ollive-ai-sde

# 2. Configure secrets
cp .env.example .env
# Edit .env — set GROQ_API_KEY (get free key at console.groq.com)

# 3. Build and start everything (one command)
docker-compose up --build

# Services:
#   Chatbot    → http://localhost:8501
#   API docs   → http://localhost:8000/docs
#   PostgreSQL → localhost:5432
```

---

## Manual Setup (no Docker)

### 1. Install dependencies

```bash
# Ingestion service
cd ingestion
pip install -r requirements.txt

# Chatbot
cd ../chatbot
pip install -r requirements.txt

# SDK (optional, for use in your own code)
cd ../sdk
pip install -e .
```

### 2. Run ingestion service

Uses **SQLite by default** — no database install needed.

```bash
cd ingestion
uvicorn app.main:app --reload --port 8000
# DB file created automatically at ingestion/ollive.db
```

To use PostgreSQL instead, set `DATABASE_URL`:
```bash
export DATABASE_URL=postgresql://ollive:ollive@localhost:5432/ollive_logs
```

### 3. Run chatbot

```bash
cd chatbot
export GROQ_API_KEY=your-key-here
export INGESTION_URL=http://localhost:8000
streamlit run app.py
# Opens at http://localhost:8501
```

---

## SDK Usage

### Groq / OpenAI-compatible providers

```python
from groq import Groq
from llm_logger import LLMLogger

raw_client = Groq(api_key="your-groq-key")
logger = LLMLogger(
    ingestion_url="http://localhost:8000",
    session_id="my-user-session",   # optional, auto-generated otherwise
    async_ship=True,                 # non-blocking (default)
    redact_pii=False,                # set True to scrub emails/phones/SSNs
)
client = logger.wrap_openai(raw_client)  # Groq is OpenAI-compatible

response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Anthropic

```python
import anthropic
from llm_logger import LLMLogger

raw_client = anthropic.Anthropic()
logger = LLMLogger(ingestion_url="http://localhost:8000")
client = logger.wrap_anthropic(raw_client)

response = client.messages.create(
    model="your-model-here",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Conversation management

```python
new_id = logger.new_conversation()           # fresh conversation
logger.set_conversation_id("existing-uuid")  # resume a conversation
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/logs` | Ingest inference log (auto-creates conversation) |
| POST | `/messages` | Store a chat message (user or assistant turn) |
| GET | `/logs` | List logs — filter by provider, model, status, conversation |
| GET | `/conversations` | List conversations, newest first |
| GET | `/conversations/{id}` | Full conversation with messages + logs |
| DELETE | `/conversations/{id}` | Delete conversation and all data |
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |

---

## Database Schema

```
conversations
  id            VARCHAR(36)  PK
  session_id    VARCHAR(255) NOT NULL  (indexed)
  title         VARCHAR(500) nullable
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
  provider          VARCHAR(64)  -- "groq", "openai", "anthropic"
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

## Architecture Notes

### Ingestion Flow
1. App calls LLM via SDK-wrapped client
2. SDK intercepts the response, extracts metadata (latency, tokens, previews, PII-redacted if enabled)
3. LogShipper fires a daemon thread → POST `/logs` to ingestion service
4. Chatbot also POSTs full messages to `/messages` for conversation replay
5. Ingestion service validates payload, upserts conversation, writes to DB

### Logging Strategy
- **Non-blocking**: logs ship in a background daemon thread — zero impact on response latency
- **Fail-safe**: if the ingestion service is down, logs are silently dropped (never crash the caller)
- **Retry**: up to 3 attempts with exponential back-off (0.25s → 0.5s → 1s), 2s socket timeout
- **PII-safe by default**: only 255-char previews are stored, not full prompt/response content

### Scaling Considerations
- Ingestion service is stateless → horizontally scalable behind a load balancer
- Switch `DATABASE_URL` to PostgreSQL for production (code supports both via SQLAlchemy)
- For high-throughput, replace threading with a message queue (Redis Streams / Kafka) and batch-write to DB
- Add a connection pool (pgBouncer) in front of PostgreSQL under load

### Failure Handling Assumptions
- SDK failures are always silent — logging is a side-channel, never the critical path
- Ingestion service crashes don't affect the chatbot (it degrades gracefully)
- Database unavailability → ingestion returns 500, SDK retries then drops the log
- Conversation resume works off the DB — if messages weren't persisted before a crash, they're lost

---

## Design Decisions

### SQLite for local dev, PostgreSQL for production
VARCHAR(36) UUIDs (not native UUID type) keep models portable across both dialects without any conditional logic.

### Fire-and-forget threading
The SDK ships logs in a daemon thread. Simple, no extra infra. Tradeoff: a killed process can lose the in-flight log. Acceptable for an observability side-channel.

### Conversation auto-creation on POST /logs
The SDK only needs a `conversation_id` — no separate "create conversation" round-trip. The ingestion endpoint upserts transparently.

### Separate POST /messages endpoint
Full message content (user + assistant turns) is stored separately from inference metadata. This enables conversation replay without storing full content in the inference log (preview-only keeps it privacy-friendly by default).

---

## Trade-offs

| Decision | Upside | Downside |
|----------|--------|----------|
| SQLite default | Zero setup, runs anywhere | Not suitable for concurrent production writes |
| `create_all` on startup | Zero-config first run | Swap for Alembic in production |
| Threading for log shipping | Simple, no extra infra | In-flight logs lost on process kill |
| Previews only in inference logs | Privacy-friendly | Can't replay full prompts from logs alone |
| Streamlit UI | Fast to build | Not suited for high-concurrency |

---

## What I'd Improve with More Time

1. **Streaming support** — intercept streamed responses, accumulate chunks, log final token count
2. **Latency / Throughput / Error dashboards** — Streamlit dashboard page reading from `/logs`
3. **Event-based architecture** — SDK publishes to Redis Streams; ingestion consumers batch-write to DB
4. **Alembic migrations** — replace `create_all` with versioned schema migrations
5. **Async ingestion** — `asyncpg` + SQLAlchemy async for burst traffic
6. **Kubernetes manifests** — Deployment + Service + ConfigMap YAMLs for each component
7. **OpenTelemetry** — emit traces alongside logs for distributed tracing
8. **Auth** — API key middleware on the ingestion service
