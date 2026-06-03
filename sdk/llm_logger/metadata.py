"""
Metadata extraction utilities for LLM inference logs.
Handles token counting, PII detection, and PII redaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE_RE = re.compile(
    r"""
    (?<!\d)
    (?:
        (?:\+?1[\s.\-]?)?          # optional country code
        (?:\(?\d{3}\)?[\s.\-]?)    # area code
        \d{3}[\s.\-]?\d{4}         # number
    )
    (?!\d)
    """,
    re.VERBOSE,
)

_SSN_RE = re.compile(
    r"\b(?!000|666|9\d{2})\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b"
)

# Credit card — basic Luhn-ish shape (13-19 digits, grouped or continuous)
_CREDIT_CARD_RE = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b"
)


@dataclass
class PIIDetectionResult:
    has_pii: bool
    detected_types: list[str] = field(default_factory=list)
    redacted_text: Optional[str] = None


def detect_pii(text: str) -> PIIDetectionResult:
    """
    Scan *text* for common PII patterns.
    Returns a PIIDetectionResult with which types were found.
    Does NOT redact — call redact_pii for that.
    """
    detected: list[str] = []

    if _EMAIL_RE.search(text):
        detected.append("email")
    if _PHONE_RE.search(text):
        detected.append("phone")
    if _SSN_RE.search(text):
        detected.append("ssn")

    return PIIDetectionResult(
        has_pii=bool(detected),
        detected_types=detected,
    )


def redact_pii(text: str) -> str:
    """
    Return a copy of *text* with detected PII replaced by placeholder tokens.
    """
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _SSN_RE.sub("[REDACTED_SSN]", text)
    return text


def extract_token_counts(response: object, provider: str) -> dict[str, int]:
    """
    Extract token usage from a provider response object.

    Supported providers: "anthropic", "openai"
    Returns a dict with keys: prompt_tokens, completion_tokens, total_tokens.
    Gracefully falls back to 0 for any missing field.
    """
    counts = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    try:
        if provider == "anthropic":
            usage = getattr(response, "usage", None)
            if usage is not None:
                counts["prompt_tokens"] = getattr(usage, "input_tokens", 0) or 0
                counts["completion_tokens"] = getattr(usage, "output_tokens", 0) or 0
                counts["total_tokens"] = (
                    counts["prompt_tokens"] + counts["completion_tokens"]
                )

        elif provider == "openai":
            usage = getattr(response, "usage", None)
            if usage is not None:
                counts["prompt_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
                counts["completion_tokens"] = (
                    getattr(usage, "completion_tokens", 0) or 0
                )
                counts["total_tokens"] = getattr(usage, "total_tokens", 0) or (
                    counts["prompt_tokens"] + counts["completion_tokens"]
                )
    except Exception:
        pass  # never crash the caller

    return counts


def extract_text_preview(text: str, max_chars: int = 200) -> str:
    """Return the first *max_chars* characters of *text*, stripped of excess whitespace."""
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned[:max_chars]


def extract_input_preview(
    messages: list[dict],
    provider: str,
    max_chars: int = 200,
) -> str:
    """
    Build a short preview of the *last user message* in the conversation.
    Falls back to the first message if no user message is found.
    """
    if not messages:
        return ""

    last_user: Optional[str] = None
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                last_user = content
            elif isinstance(content, list):
                # Anthropic-style content blocks
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                last_user = " ".join(parts)
            break

    return extract_text_preview(last_user or "", max_chars)


def extract_output_preview(response: object, provider: str, max_chars: int = 200) -> str:
    """Extract a short preview of the model's response text."""
    text = ""
    try:
        if provider == "anthropic":
            content = getattr(response, "content", [])
            parts = []
            for block in content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            text = " ".join(parts)

        elif provider == "openai":
            choices = getattr(response, "choices", [])
            if choices:
                msg = getattr(choices[0], "message", None)
                if msg:
                    text = getattr(msg, "content", "") or ""
    except Exception:
        pass

    return extract_text_preview(text, max_chars)
