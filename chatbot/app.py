"""
Streamlit chatbot powered by Llama 3.3 70B (Groq) via the LLMLogger SDK.

Features:
- Multi-turn conversations with message history
- Sidebar listing all conversations (fetched from ingestion API)
- Resume a past conversation by clicking it
- Delete a conversation from the sidebar
- New conversation button
- Per-message latency and token count display
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime
from typing import Optional

from groq import Groq
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Allow importing llm_logger from the SDK directory if running locally
# ---------------------------------------------------------------------------
_SDK_PATH = os.path.join(os.path.dirname(__file__), "..", "sdk")
if os.path.isdir(_SDK_PATH) and _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

try:
    from llm_logger import LLMLogger
    _HAS_LOGGER = True
except ImportError:
    _HAS_LOGGER = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
INGESTION_URL: str = os.environ.get("INGESTION_URL", "http://localhost:8000")
MODEL: str = "llama-3.3-70b-versatile"
MAX_TOKENS: int = 1024

# ---------------------------------------------------------------------------
# Streamlit page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM Chat",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Helpers for the ingestion API
# ---------------------------------------------------------------------------

def _api(path: str, method: str = "GET", **kwargs) -> Optional[dict]:
    """Make a request to the ingestion service. Returns None on failure."""
    try:
        url = INGESTION_URL.rstrip("/") + path
        resp = requests.request(method, url, timeout=5, **kwargs)
        resp.raise_for_status()
        if resp.status_code == 204:
            return {}
        return resp.json()
    except Exception:
        return None


def fetch_conversations() -> list[dict]:
    data = _api("/conversations?page_size=100")
    if data is None:
        return []
    return data.get("items", [])


def fetch_conversation_detail(conv_id: str) -> Optional[dict]:
    return _api(f"/conversations/{conv_id}")


def delete_conversation_api(conv_id: str) -> bool:
    result = _api(f"/conversations/{conv_id}", method="DELETE")
    return result is not None


def fetch_logs_for_conversation(conv_id: str) -> list[dict]:
    data = _api(f"/logs?conversation_id={conv_id}&page_size=200")
    if data is None:
        return []
    return data.get("items", [])


def save_message(conv_id: str, role: str, content: str, session_id: str) -> Optional[dict]:
    """Persist a single chat message to the ingestion service."""
    return _api(
        "/messages",
        method="POST",
        json={"conversation_id": conv_id, "role": role, "content": content, "session_id": session_id},
    )


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_state() -> None:
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        # Each entry: {"role": str, "content": str, "meta": dict | None}
        st.session_state.messages = []
    if "llm_logger" not in st.session_state:
        st.session_state.llm_logger = None
    if "anthropic_client" not in st.session_state:
        st.session_state.anthropic_client = None
    if "conv_list" not in st.session_state:
        st.session_state.conv_list = []
    if "last_conv_refresh" not in st.session_state:
        st.session_state.last_conv_refresh = 0.0
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())


def _get_or_build_client():
    """Return the (possibly wrapped) Anthropic client, building it once."""
    if st.session_state.anthropic_client is not None:
        return st.session_state.anthropic_client

    raw_client = Groq(api_key=GROQ_API_KEY)

    if _HAS_LOGGER:
        llm_logger = LLMLogger(
            ingestion_url=INGESTION_URL,
            session_id=st.session_state.session_id,
            async_ship=True,
            conversation_id=st.session_state.conversation_id,
        )
        st.session_state.llm_logger = llm_logger
        client = llm_logger.wrap_openai(raw_client)  # Groq is OpenAI-compatible
    else:
        client = raw_client

    st.session_state.anthropic_client = client
    return client


def _refresh_conversations(force: bool = False) -> None:
    now = time.time()
    if force or (now - st.session_state.last_conv_refresh) > 10:
        st.session_state.conv_list = fetch_conversations()
        st.session_state.last_conv_refresh = now


def _start_new_conversation() -> None:
    new_id = str(uuid.uuid4())
    st.session_state.conversation_id = new_id
    st.session_state.messages = []
    # rebuild client with new conversation id
    st.session_state.anthropic_client = None
    st.session_state.llm_logger = None
    _refresh_conversations(force=True)
    st.rerun()


def _load_conversation(conv_id: str) -> None:
    """Load messages for an existing conversation from the API."""
    detail = fetch_conversation_detail(conv_id)
    if detail is None:
        st.error("Could not load conversation.")
        return

    st.session_state.conversation_id = conv_id
    st.session_state.messages = []
    st.session_state.anthropic_client = None
    st.session_state.llm_logger = None

    raw_messages = sorted(detail.get("messages", []), key=lambda m: m["created_at"])
    logs = {lg["message_id"]: lg for lg in detail.get("inference_logs", []) if lg.get("message_id")}

    for msg in raw_messages:
        meta = None
        if msg["id"] in logs:
            lg = logs[msg["id"]]
            meta = {
                "latency_ms": lg.get("latency_ms", 0),
                "total_tokens": lg.get("total_tokens", 0),
                "prompt_tokens": lg.get("prompt_tokens", 0),
                "completion_tokens": lg.get("completion_tokens", 0),
            }
        st.session_state.messages.append(
            {"role": msg["role"], "content": msg["content"], "meta": meta}
        )

    st.rerun()


def _delete_conversation(conv_id: str) -> None:
    ok = delete_conversation_api(conv_id)
    if ok and st.session_state.conversation_id == conv_id:
        _start_new_conversation()
        return
    _refresh_conversations(force=True)
    st.rerun()


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("Conversations")

        if st.button("New conversation", use_container_width=True, type="primary"):
            _start_new_conversation()

        st.divider()

        if st.button("Refresh list", use_container_width=True):
            _refresh_conversations(force=True)

        convs = st.session_state.conv_list
        if not convs:
            st.caption("No conversations yet.")
            return

        for conv in convs:
            cid = conv["id"]
            title = conv.get("title") or f"Conv {cid[:8]}…"
            ts = conv.get("updated_at", "")[:16].replace("T", " ")
            is_active = cid == st.session_state.conversation_id

            label = f"{'▶ ' if is_active else ''}{title}\n{ts}"

            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(
                    label,
                    key=f"load_{cid}",
                    use_container_width=True,
                    type="secondary" if not is_active else "primary",
                ):
                    _load_conversation(cid)
            with col2:
                if st.button("🗑", key=f"del_{cid}", help="Delete conversation"):
                    _delete_conversation(cid)


def render_chat() -> None:
    st.title("LLM Chat")
    st.caption(f"Model: `{MODEL}` · Conversation: `{st.session_state.conversation_id[:8]}…`")

    # Display existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("meta"):
                meta = msg["meta"]
                st.caption(
                    f"Latency: {meta.get('latency_ms', '?')} ms · "
                    f"Tokens in: {meta.get('prompt_tokens', '?')} · "
                    f"Tokens out: {meta.get('completion_tokens', '?')} · "
                    f"Total: {meta.get('total_tokens', '?')}"
                )

    # Chat input
    if not GROQ_API_KEY:
        st.error("GROQ_API_KEY is not set. Set it in your .env file.")
        return

    user_input = st.chat_input("Type a message…")
    if not user_input:
        return

    # Show user message immediately and persist it
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append(
        {"role": "user", "content": user_input, "meta": None}
    )
    save_message(
        st.session_state.conversation_id, "user", user_input, st.session_state.session_id
    )

    # Build messages list for the API (no meta, just role + content)
    api_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    client = _get_or_build_client()

    # Update logger's conversation id in case it was rebuilt
    if st.session_state.llm_logger is not None:
        st.session_state.llm_logger.set_conversation_id(
            st.session_state.conversation_id
        )

    with st.chat_message("assistant"):
        placeholder = st.empty()
        with st.spinner("Thinking…"):
            t0 = time.monotonic()
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=api_messages,
                )
                elapsed_ms = int((time.monotonic() - t0) * 1000)

                assistant_text = response.choices[0].message.content or ""

                # Token counts from response
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
                total_tokens = prompt_tokens + completion_tokens

                placeholder.markdown(assistant_text)
                st.caption(
                    f"Latency: {elapsed_ms} ms · "
                    f"Tokens in: {prompt_tokens} · "
                    f"Tokens out: {completion_tokens} · "
                    f"Total: {total_tokens}"
                )

                meta = {
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                st.session_state.messages.append(
                    {"role": "assistant", "content": assistant_text, "meta": meta}
                )
                save_message(
                    st.session_state.conversation_id, "assistant", assistant_text, st.session_state.session_id
                )

            except Exception as exc:
                placeholder.error(f"Error: {exc}")

    _refresh_conversations(force=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _init_state()
    _refresh_conversations()
    render_sidebar()
    render_chat()


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module at import time
    main()
