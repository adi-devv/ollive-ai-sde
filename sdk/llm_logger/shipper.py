"""
Fire-and-forget async HTTP log shipping.

Logs are shipped in a background thread so they never block the caller.
Failed attempts are retried up to MAX_RETRIES times with exponential back-off.
If the ingestion service is unreachable the failure is silently swallowed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional
from urllib import request, error as urllib_error

logger = logging.getLogger(__name__)

MAX_RETRIES: int = 3
TIMEOUT_SECONDS: float = 2.0
BASE_BACKOFF_SECONDS: float = 0.25  # doubles on each retry


def _post_with_retry(url: str, payload: dict[str, Any]) -> None:
    """
    Attempt to POST *payload* (JSON) to *url* up to MAX_RETRIES times.
    Runs entirely inside a daemon thread — never raises to the caller.
    """
    data = json.dumps(payload, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = request.Request(url, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                if resp.status < 300:
                    return  # success
                logger.debug(
                    "Shipper: HTTP %s on attempt %d, will %s",
                    resp.status,
                    attempt,
                    "retry" if attempt < MAX_RETRIES else "give up",
                )
        except urllib_error.URLError as exc:
            logger.debug(
                "Shipper: network error on attempt %d: %s", attempt, exc
            )
        except OSError as exc:
            logger.debug(
                "Shipper: OS error on attempt %d: %s", attempt, exc
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Shipper: unexpected error on attempt %d: %s", attempt, exc
            )

        if attempt < MAX_RETRIES:
            backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(backoff)


class LogShipper:
    """
    Non-blocking log shipper.

    Call :meth:`ship` and the payload will be sent in a daemon thread.
    The calling thread is never blocked and errors never propagate.
    """

    def __init__(self, ingestion_url: str) -> None:
        self.ingestion_url = ingestion_url.rstrip("/") + "/logs"

    def ship(self, payload: dict[str, Any]) -> Optional[threading.Thread]:
        """
        Dispatch *payload* to the ingestion service in a background thread.
        Returns the thread object (mostly useful for testing).
        """
        t = threading.Thread(
            target=_post_with_retry,
            args=(self.ingestion_url, payload),
            daemon=True,
            name="llm-log-shipper",
        )
        t.start()
        return t

    def ship_sync(self, payload: dict[str, Any]) -> None:
        """
        Synchronous variant — blocks until the POST completes or all retries
        are exhausted.  Useful for unit tests or flush-on-exit scenarios.
        """
        _post_with_retry(self.ingestion_url, payload)
