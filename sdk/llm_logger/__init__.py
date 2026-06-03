"""
llm_logger — lightweight SDK for capturing LLM inference metadata.

Quick-start::

    from llm_logger import LLMLogger
    import anthropic

    client = anthropic.Anthropic()
    llm_logger = LLMLogger(ingestion_url="http://localhost:8000")
    client = llm_logger.wrap_anthropic(client)

    # All subsequent client.messages.create() calls are logged automatically.
"""

from .logger import LLMLogger
from .metadata import PIIDetectionResult, detect_pii, redact_pii
from .shipper import LogShipper

__all__ = [
    "LLMLogger",
    "LogShipper",
    "PIIDetectionResult",
    "detect_pii",
    "redact_pii",
]

__version__ = "0.1.0"
