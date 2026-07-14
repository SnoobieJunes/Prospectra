# 2026-07-14 (P5): Emitters — scraped tables become ordinary files in the project's staging folder,
# which is the whole point of the design: once a table is a CSV on disk it is just another file
# dataset, so it feeds the catalog, the flow canvas, and the miner with zero special-casing.
#
# Windows rule (CLAUDE.md): CSVs are written through a handle opened with newline="" — pandas would
# otherwise emit \r\r\n line endings on Windows and every downstream reader would see blank rows.

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from prospectra.core.scraper.parser import ScrapedArticle, ScrapedTable

logger = logging.getLogger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
MAX_SLUG_LENGTH = 60


def slugify(text: str, fallback: str = "table") -> str:
    slug = _SLUG_STRIP.sub("_", text.lower()).strip("_")[:MAX_SLUG_LENGTH].strip("_")
    return slug or fallback


@dataclass(frozen=True)
class EmittedFile:
    path: Path
    name: str  # the table's human name
    rows: int
    columns: int


def emit_tables(
    tables: list[ScrapedTable], staging: Path, *, prefix: str = ""
) -> list[EmittedFile]:
    """Write one CSV per table into `staging`. Returns what was written, in page order."""
    staging.mkdir(parents=True, exist_ok=True)
    written: list[EmittedFile] = []
    used: set[str] = set()
    for table in tables:
        stem = slugify(f"{prefix}_{table.name}" if prefix else table.name)
        candidate = stem
        suffix = 2
        while candidate in used:  # two tables can share a caption on one page
            candidate = f"{stem}_{suffix}"
            suffix += 1
        used.add(candidate)
        path = staging / f"{candidate}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:  # newline="": Windows rule
            table.frame.to_csv(handle, index=False)
        written.append(
            EmittedFile(
                path=path,
                name=table.name,
                rows=len(table.frame),
                columns=len(table.frame.columns),
            )
        )
        logger.info("Wrote %s (%d rows)", path, len(table.frame))
    return written


def emit_article(article: ScrapedArticle, staging: Path, url: str, *, prefix: str = "") -> Path:
    """Write the page's text as JSON — usable as a file dataset, and as LLM context later."""
    staging.mkdir(parents=True, exist_ok=True)
    stem = slugify(prefix or article.title or "page", fallback="page")
    path = staging / f"{stem}.json"
    payload = {"url": url, "title": article.title, "text": article.text}
    with path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path
