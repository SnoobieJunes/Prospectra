# 2026-07-14 (P5): The scraper — fetch (robots.txt + rate limited) → parse (tables / article) →
# emit (CSV/JSON into project staging, where they become ordinary file datasets).

from prospectra.core.scraper.emitter import EmittedFile, emit_article, emit_tables, slugify
from prospectra.core.scraper.errors import (
    FetchError,
    NothingExtracted,
    RobotsDisallowed,
    ScraperError,
)
from prospectra.core.scraper.fetcher import (
    USER_AGENT,
    Fetcher,
    HttpFetcher,
    LocalFileFetcher,
    Page,
    default_fetcher,
)
from prospectra.core.scraper.parser import (
    ScrapedArticle,
    ScrapedTable,
    extract_article,
    extract_tables,
)
from prospectra.core.scraper.pipeline import ScrapeResult, scrape
from prospectra.core.scraper.rate_limit import RateLimiter
from prospectra.core.scraper.robots import RobotsCache, RobotsRules, parse_robots

__all__ = [
    "USER_AGENT",
    "EmittedFile",
    "FetchError",
    "Fetcher",
    "HttpFetcher",
    "LocalFileFetcher",
    "NothingExtracted",
    "Page",
    "RateLimiter",
    "RobotsCache",
    "RobotsDisallowed",
    "RobotsRules",
    "ScrapeResult",
    "ScrapedArticle",
    "ScrapedTable",
    "ScraperError",
    "default_fetcher",
    "emit_article",
    "emit_tables",
    "extract_article",
    "extract_tables",
    "parse_robots",
    "scrape",
    "slugify",
]
