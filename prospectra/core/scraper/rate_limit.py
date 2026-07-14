# 2026-07-14 (P5): Per-host rate limiting — a minimum interval between requests to the same host,
# raised (never lowered) by that host's robots.txt Crawl-delay.
# Why per-host and not global: politeness is owed to a *server*, not to the internet. Two hosts can
# be fetched back to back; one host cannot.
# The clock and sleep are injected so the behaviour is testable without actually waiting.

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlparse

DEFAULT_MIN_INTERVAL = 1.0  # seconds between requests to one host


class RateLimiter:
    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}  # host -> time of its last request
        self._host_interval: dict[str, float] = {}

    def set_host_interval(self, url: str, interval: float) -> None:
        """A host-specific interval (e.g. robots.txt Crawl-delay). Never below the default."""
        host = urlparse(url).netloc
        self._host_interval[host] = max(interval, self.min_interval)

    def interval_for(self, url: str) -> float:
        return self._host_interval.get(urlparse(url).netloc, self.min_interval)

    def wait(self, url: str) -> float:
        """Block until this host may be hit again. Returns the number of seconds waited."""
        host = urlparse(url).netloc
        interval = self.interval_for(url)
        now = self._clock()
        last = self._last.get(host)
        waited = 0.0
        if last is not None:
            remaining = interval - (now - last)
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining
        self._last[host] = self._clock()
        return waited
