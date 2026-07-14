# 2026-07-14 (P5): The scrape pipeline — fetch → parse → emit, wired together.
#
# This is the only function the CLI and the UI call. It is deliberately synchronous and pure of Qt:
# the UI runs it on a worker thread like every other engine call. The fetcher is injectable, so the
# whole path (including the CLI) is exercised in CI against local HTML with no network.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from prospectra.core.scraper.emitter import EmittedFile, emit_article, emit_tables, slugify
from prospectra.core.scraper.errors import NothingExtracted
from prospectra.core.scraper.fetcher import Fetcher, default_fetcher
from prospectra.core.scraper.parser import ScrapedTable, extract_article, extract_tables

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScrapeResult:
    url: str
    final_url: str
    tables: list[ScrapedTable] = field(default_factory=list)
    files: list[EmittedFile] = field(default_factory=list)  # the CSVs written for those tables
    article_path: Path | None = None  # set only when the page had no tables
    article_title: str = ""

    @property
    def summary(self) -> str:
        if self.files:
            return f"{len(self.files)} table(s) from {self.final_url}"
        if self.article_path is not None:
            return f"article text from {self.final_url} (no tables on the page)"
        return f"nothing extracted from {self.final_url}"


def _page_prefix(url: str) -> str:
    parsed = urlparse(url)
    last = [p for p in parsed.path.split("/") if p]
    return slugify(last[-1]) if last else slugify(parsed.netloc, fallback="page")


def scrape(
    url: str,
    staging: Path,
    *,
    fetcher: Fetcher | None = None,
    tables_only: bool = False,
    max_tables: int | None = None,
) -> ScrapeResult:
    """Fetch a page, extract its tables into `staging` as CSVs, and report what landed.

    Falls back to the page's article text (as JSON) when there are no tables — unless
    `tables_only`, where a page with no tables is an error the caller should see.
    """
    active = fetcher or default_fetcher(url)
    page = active.fetch(url)
    prefix = _page_prefix(page.final_url)

    tables = extract_tables(page.html)
    if max_tables is not None:
        tables = tables[:max_tables]

    if tables:
        files = emit_tables(tables, staging, prefix=prefix)
        return ScrapeResult(url=url, final_url=page.final_url, tables=tables, files=files)

    if tables_only:
        raise NothingExtracted(f"No data tables found on {page.final_url}")

    article = extract_article(page.html)
    if not article.text:
        raise NothingExtracted(f"No tables and no article text found on {page.final_url}")
    path = emit_article(article, staging, page.final_url, prefix=prefix)
    return ScrapeResult(
        url=url,
        final_url=page.final_url,
        article_path=path,
        article_title=article.title,
    )
