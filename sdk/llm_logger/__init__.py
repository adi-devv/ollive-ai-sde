"""
llm_logger — lightweight SDK for capturing LLM inference metadata.

Quick-start::

    from groq import Groq
    from llm_logger import LLMLogger

    client = Groq(api_key="your-key")
    llm_logger = LLMLogger(ingestion_url="http://localhost:8000")
    client = llm_logger.wrap_openai(client)  # Groq is OpenAI-compatible

    # All subsequent client.chat.completions.create() calls are logged automatically.
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
