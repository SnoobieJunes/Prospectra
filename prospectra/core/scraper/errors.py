# 2026-07-14 (P5): Scraper error types. Separated from the pipeline so callers (CLI, UI, tests)
# can distinguish "the site said no" from "the network broke" from "there was nothing to extract" —
# the three cases need different words in front of a user.

from __future__ import annotations


class ScraperError(Exception):
    """Base error for scraper failures."""


class RobotsDisallowed(ScraperError):
    """The site's robots.txt forbids this user agent from fetching this URL.

    This is a refusal, not a failure: we obey it rather than working around it.
    """


class FetchError(ScraperError):
    """The page could not be fetched (network, timeout, HTTP status, size cap)."""


class NothingExtracted(ScraperError):
    """The page was fetched but held no table (and no article text) to emit."""
