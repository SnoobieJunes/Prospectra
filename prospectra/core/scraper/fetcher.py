# 2026-07-14 (P5): Fetchers — the only part of the scraper that touches the network.
#
# `Fetcher` is a Protocol, so the pipeline never depends on httpx: tests inject a canned fetcher,
# and `LocalFileFetcher` re-parses a page already saved to disk (also what makes the CLI's scrape
# path exercisable in CI with no network).
#
# HttpFetcher's guarantees, in order of when they apply:
#   1. robots.txt is consulted first — a disallow raises RobotsDisallowed and no request is made.
#   2. the per-host rate limit is honoured (raised by robots.txt Crawl-delay when the site asks).
#   3. redirects are followed, then the *final* URL is re-checked against robots.txt.
#   4. a byte cap aborts oversized responses instead of buying the whole file into memory.
#   5. non-HTML content types are refused with a clear message rather than parsed as garbage.

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from prospectra.core.scraper.errors import FetchError, RobotsDisallowed
from prospectra.core.scraper.rate_limit import DEFAULT_MIN_INTERVAL, RateLimiter
from prospectra.core.scraper.robots import RobotsCache

logger = logging.getLogger(__name__)

USER_AGENT = "ProspectraBot/0.1 (+https://github.com/SnoobieJunes/Prospectra)"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB of HTML is already an outlier


@dataclass(frozen=True)
class Page:
    url: str  # the URL asked for
    final_url: str  # after redirects — what the HTML actually describes
    html: str
    status: int = 200


class Fetcher(Protocol):
    def fetch(self, url: str) -> Page: ...


class LocalFileFetcher:
    """Reads a page off disk. For `file://` URLs, saved pages, and tests — never the network."""

    def fetch(self, url: str) -> Page:
        parsed = urlparse(url)
        path = Path(parsed.path if parsed.scheme == "file" else url)
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise FetchError(f"Could not read {path}: {exc}") from exc
        return Page(url=url, final_url=path.resolve().as_uri(), html=html)


class HttpFetcher:
    """httpx + robots.txt + per-host rate limiting."""

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        obey_robots: bool = True,
    ) -> None:
        import httpx  # deferred: keeps `import prospectra.core` cheap for non-scraping paths

        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.obey_robots = obey_robots
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
        self._limiter = RateLimiter(min_interval)
        self._robots = RobotsCache(self._fetch_robots)

    # -- robots ------------------------------------------------------------------------------

    def _fetch_robots(self, url: str) -> str | None:
        import httpx

        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            return None  # unreachable robots.txt → permissive, per the standard
        if response.status_code >= 400:
            return None
        return response.text

    def _check_allowed(self, url: str) -> None:
        if not self.obey_robots:
            return
        rules = self._robots.rules_for(url)
        if not rules.allows(url, self.user_agent):
            raise RobotsDisallowed(
                f"{urlparse(url).netloc}'s robots.txt disallows fetching {url}. "
                "Prospectra obeys robots.txt — it will not fetch this page."
            )
        delay = rules.crawl_delay(self.user_agent)
        if delay is not None:
            self._limiter.set_host_interval(url, delay)

    # -- fetching ----------------------------------------------------------------------------

    def fetch(self, url: str) -> Page:
        import httpx

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise FetchError(f"Only http(s) URLs can be scraped — got {url!r}")

        self._check_allowed(url)
        self._limiter.wait(url)

        try:
            with self._client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise FetchError(f"{url} returned HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if content_type and "html" not in content_type and "xml" not in content_type:
                    raise FetchError(
                        f"{url} is {content_type.split(';')[0]}, not a web page. Open it as a data "
                        "file instead (Sources ▸ Open File…)."
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FetchError(
                            f"{url} is larger than the {self.max_bytes // 1024 // 1024} MB page cap"
                        )
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                final_url = str(response.url)
                status = response.status_code
        except httpx.HTTPError as exc:
            raise FetchError(f"Could not fetch {url}: {exc}") from exc

        # A redirect can land somewhere robots.txt forbids; the destination gets checked too.
        if final_url != url:
            self._check_allowed(final_url)

        html = b"".join(chunks).decode(encoding, errors="replace")
        logger.info("Fetched %s (%d bytes)", final_url, size)
        return Page(url=url, final_url=final_url, html=html, status=status)

    def close(self) -> None:
        self._client.close()


def default_fetcher(url: str) -> Fetcher:
    """Pick the fetcher a URL needs: local paths and file:// stay off the network."""
    scheme = urlparse(url).scheme
    if scheme in ("http", "https"):
        return HttpFetcher()
    return LocalFileFetcher()
