"""
LLMLogger — intercepts calls to Groq / OpenAI-compatible clients,
captures inference metadata, and ships logs to the ingestion service.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .metadata import (
    detect_pii,
    extract_input_preview,
    extract_output_preview,
    extract_token_counts,
    redact_pii,
)
from .shipper import LogShipper

_log = logging.getLogger(__name__)


class _AnthropicMessagesProxy:
    """Wraps ``client.messages`` so ``.create()`` calls are intercepted."""

    def __init__(
        self,
        original_messages: Any,
        llm_logger: "LLMLogger",
    ) -> None:
        self._original = original_messages
        self._llm_logger = llm_logger

    def create(self, **kwargs: Any) -> Any:
        return self._llm_logger._anthropic_create(self._original, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Pass through any other attribute (e.g., .stream, .batches)
        return getattr(self._original, name)


class _AnthropicClientProxy:
    """Thin wrapper around an Anthropic client that swaps out ``.messages``."""

    def __init__(self, client: Any, llm_logger: "LLMLogger") -> None:
        self._client = client
        self._llm_logger = llm_logger
        self.messages = _AnthropicMessagesProxy(client.messages, llm_logger)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _OpenAIChatCompletionsProxy:
    """Wraps ``client.chat.completions`` so ``.create()`` is intercepted."""

    def __init__(
        self,
        original_completions: Any,
        llm_logger: "LLMLogger",
    ) -> None:
        self._original = original_completions
        self._llm_logger = llm_logger

    def create(self, **kwargs: Any) -> Any:
        return self._llm_logger._openai_create(self._original, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _OpenAIChatProxy:
    def __init__(self, original_chat: Any, llm_logger: "LLMLogger") -> None:
        self._chat = original_chat
        self.completions = _OpenAIChatCompletionsProxy(
            original_chat.completions, llm_logger
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class _OpenAIClientProxy:
    """Thin wrapper around an OpenAI client that swaps out ``.chat``."""

    def __init__(self, client: Any, llm_logger: "LLMLogger") -> None:
        self._client = client
        self._llm_logger = llm_logger
        self.chat = _OpenAIChatProxy(client.chat, llm_logger)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class LLMLogger:
    """
    Wraps LLM client objects to capture inference metadata and ship logs.

    Usage::

        from groq import Groq
        from llm_logger import LLMLogger

        client = Groq(api_key="your-key")
        logger = LLMLogger(ingestion_url="http://localhost:8000")
        client = logger.wrap_openai(client)  # Groq is OpenAI-compatible

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Hello!"}],
        )

    Parameters
    ----------
    ingestion_url:
        Base URL of the ingestion service (e.g. ``"http://localhost:8000"``).
    session_id:
        Optional stable identifier for the current user session.
        Auto-generated (UUID4) if omitted.
    async_ship:
        When *True* (default) logs are shipped in a background thread and
        never block the caller.  Set to *False* to ship synchronously (useful
        for testing).
    redact_pii:
        When *True*, detected PII is replaced with placeholder tokens in the
        input/output previews before they are stored.
    conversation_id:
        Fixed conversation UUID.  When *None* a new UUID is generated per
        :meth:`wrap_openai` call.
    """

    def __init__(
        self,
        ingestion_url: str,
        session_id: Optional[str] = None,
        async_ship: bool = True,
        redact_pii: bool = False,
        conversation_id: Optional[str] = None,
    ) -> None:
        self.ingestion_url = ingestion_url
        self.session_id: str = session_id or str(uuid.uuid4())
        self.async_ship = async_ship
        self._redact_pii = redact_pii
        self.conversation_id: str = conversation_id or str(uuid.uuid4())

        self._shipper = LogShipper(ingestion_url)

    # ------------------------------------------------------------------
    # Public wrap helpers
    # ------------------------------------------------------------------

    def wrap_anthropic(self, client: Any) -> Any:
        """Return a proxy that intercepts Anthropic-style ``.messages.create()`` calls."""
        return _AnthropicClientProxy(client, self)

    def wrap_openai(self, client: Any) -> Any:
        """Return a proxy that intercepts ``.chat.completions.create()`` calls."""
        return _OpenAIClientProxy(client, self)

    def set_conversation_id(self, conversation_id: str) -> None:
        """Switch the active conversation context."""
        self.conversation_id = conversation_id

    def new_conversation(self) -> str:
        """Generate and activate a fresh conversation ID, return it."""
        self.conversation_id = str(uuid.uuid4())
        return self.conversation_id

    # ------------------------------------------------------------------
    # Internal interception helpers
    # ------------------------------------------------------------------

    def _anthropic_create(self, original_messages: Any, **kwargs: Any) -> Any:
        model: str = kwargs.get("model", "unknown")
        messages: list[dict] = kwargs.get("messages", [])

        t0 = time.monotonic()
        error_message: Optional[str] = None
        response: Any = None
        status = "success"

        try:
            response = original_messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_message = str(exc)
            _log.debug("Anthropic call failed: %s", exc)
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._ship_log(
                provider="anthropic",
                model=model,
                messages=messages,
                response=response,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )

        return response

    def _openai_create(self, original_completions: Any, **kwargs: Any) -> Any:
        model: str = kwargs.get("model", "unknown")
        messages: list[dict] = kwargs.get("messages", [])

        t0 = time.monotonic()
        error_message: Optional[str] = None
        response: Any = None
        status = "success"

        try:
            response = original_completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_message = str(exc)
            _log.debug("OpenAI call failed: %s", exc)
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._ship_log(
                provider="openai",
                model=model,
                messages=messages,
                response=response,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )

        return response

    def _ship_log(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict],
        response: Any,
        latency_ms: int,
        status: str,
        error_message: Optional[str],
    ) -> None:
        try:
            tokens = extract_token_counts(response, provider)
            input_preview = extract_input_preview(messages, provider)
            output_preview = extract_output_preview(response, provider)

            if self._redact_pii:
                input_preview = redact_pii(input_preview)
                output_preview = redact_pii(output_preview)

            payload: dict[str, Any] = {
                "conversation_id": self.conversation_id,
                "session_id": self.session_id,
                "model": model,
                "provider": provider,
                "latency_ms": latency_ms,
                "prompt_tokens": tokens["prompt_tokens"],
                "completion_tokens": tokens["completion_tokens"],
                "total_tokens": tokens["total_tokens"],
                "request_status": status,
                "error_message": error_message,
                "input_preview": input_preview[:255],
                "output_preview": output_preview[:255],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if self.async_ship:
                self._shipper.ship(payload)
            else:
                self._shipper.ship_sync(payload)

        except Exception as exc:  # noqa: BLE001
            # Logging must NEVER crash the caller
            _log.debug("LLMLogger: failed to build/ship log: %s", exc)
