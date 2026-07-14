# 2026-07-14 (P5): robots.txt — fetched once per host, cached, and consulted before every request.
# Why this is not optional: a scraper that ignores robots.txt is a scraper that gets its users'
# IP ranges banned, and it is the single clearest line between "tool" and "abuse". A host whose
# robots.txt cannot be fetched (404/network error) is treated as permissive — that is what the
# standard says absence means — but a host that *answers* with a disallow is obeyed, always.
#
# The crawl-delay directive, when present, raises the per-host rate limit (never lowers it): if a
# site asks for 10 s between requests, it gets 10 s, not our 1 s default.

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RobotsRules:
    """One host's robots.txt, already parsed. `missing` means "no file" → everything allowed."""

    parser: RobotFileParser
    missing: bool

    def allows(self, url: str, user_agent: str) -> bool:
        if self.missing:
            return True
        return bool(self.parser.can_fetch(user_agent, url))

    def crawl_delay(self, user_agent: str) -> float | None:
        if self.missing:
            return None
        try:
            delay = self.parser.crawl_delay(user_agent)
        except Exception:  # a malformed file must never take the scraper down
            return None
        return float(delay) if delay is not None else None


def robots_url_for(url: str) -> str:
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, "/robots.txt", "", "", ""))


def parse_robots(text: str) -> RobotsRules:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return RobotsRules(parser=parser, missing=False)


def no_robots() -> RobotsRules:
    """The permissive default used when a host serves no robots.txt (absence == allowed)."""
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Allow: /"])
    return RobotsRules(parser=parser, missing=True)


class RobotsCache:
    """Per-host robots.txt cache. `fetch_text` is injected so tests never touch the network."""

    def __init__(self, fetch_text: Callable[[str], str | None]) -> None:
        """`fetch_text(url)` returns robots.txt's text, or None when the host serves no file."""
        self._fetch_text = fetch_text
        self._hosts: dict[str, RobotsRules] = {}

    def rules_for(self, url: str) -> RobotsRules:
        host = urlparse(url).netloc
        cached = self._hosts.get(host)
        if cached is not None:
            return cached
        try:
            text = self._fetch_text(robots_url_for(url))
        except Exception as exc:  # unreachable robots.txt is not a reason to refuse the page
            logger.info("Could not read robots.txt for %s (%s) — treating as permissive", host, exc)
            text = None
        rules = no_robots() if text is None else parse_robots(text)
        self._hosts[host] = rules
        return rules
