# 2026-07-14 (P5): Parsing — HTML in, tabular data (and article text) out.
#
# Tables are located with BeautifulSoup first, then handed to pandas.read_html *one at a time*,
# because the caption matters as much as the numbers: a Wikipedia page has a dozen tables and
# "table_3.csv" tells the user nothing. Each table keeps the caption (or the nearest preceding
# heading) as its name.
#
# Header cleaning is not cosmetic — these column names become SQL identifiers downstream. Wikipedia
# ships footnote markers ("Population[a]"), multi-row headers (pandas gives a MultiIndex), unnamed
# columns, and duplicates; all four would produce unusable or colliding column names in a flow.

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from io import StringIO
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 2026-07-14 (P5): both floors were set by what a real Wikipedia page actually contains. A live
# scrape of "List of countries by GDP (nominal)" emitted the page's *map legend* as a dataset — a
# 1-row, 2-column table of colour bands. A data table has more than one row; a legend does not.
MIN_ROWS = 2
MIN_COLUMNS = 2  # a one-column "table" is almost always page furniture

_FOOTNOTE = re.compile(r"\[\s*[a-zA-Z0-9]{1,3}\s*\]")  # [1], [a], [note]
_WHITESPACE = re.compile(r"\s+")
_UNNAMED = re.compile(r"^Unnamed:?\s*\d*(_level_\d+)?$")


@dataclass(frozen=True)
class ScrapedTable:
    name: str  # caption / nearest heading, or "table_2"
    frame: pd.DataFrame
    index: int  # position of the table on the page (0-based)

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.frame), len(self.frame.columns))


@dataclass(frozen=True)
class ScrapedArticle:
    title: str
    text: str


def _clean_cell(value: Any) -> str:
    text = _FOOTNOTE.sub("", str(value))
    return _WHITESPACE.sub(" ", text).strip()


def _flatten(name: Any) -> str:
    """One header cell -> one clean name. MultiIndex tuples collapse to their distinct parts."""
    parts = name if isinstance(name, tuple) else (name,)
    cleaned: list[str] = []
    for part in parts:
        text = _clean_cell(part)
        if not text or _UNNAMED.match(text):
            continue
        if text not in cleaned:  # pandas repeats the parent label across spanned columns
            cleaned.append(text)
    return " ".join(cleaned)


def clean_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every column a usable, unique name (they become SQL identifiers downstream)."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for position, raw in enumerate(frame.columns):
        name = _flatten(raw) or f"column_{position + 1}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        names.append(name if count == 0 else f"{name}_{count + 1}")
    out = frame.copy()
    out.columns = names
    return out


def _caption_for(table: Any, position: int) -> str:
    caption = table.find("caption")
    if caption is not None:
        text = _clean_cell(caption.get_text(" "))
        if text:
            return text
    heading = table.find_previous(["h1", "h2", "h3", "h4"])
    if heading is not None:
        text = _clean_cell(heading.get_text(" "))
        if text:
            return text
    return f"table_{position + 1}"


def extract_tables(html: str, *, min_rows: int = MIN_ROWS) -> list[ScrapedTable]:
    """Every real data table on the page, named and with cleaned headers.

    Page furniture (map legends, nav boxes: fewer than two columns or fewer than two rows) is
    dropped — emitting it as a CSV would bury the table the user actually came for.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    tables: list[ScrapedTable] = []
    for position, element in enumerate(soup.find_all("table")):
        try:
            frames = pd.read_html(StringIO(str(element)), flavor="lxml")
        except ValueError:
            continue  # read_html raises when a <table> holds no parseable rows
        except Exception:  # a malformed table must not abort the whole page
            logger.warning("Could not parse table %d on the page", position, exc_info=True)
            continue
        if not frames:
            continue
        frame = clean_columns(frames[0])
        if len(frame) < min_rows or len(frame.columns) < MIN_COLUMNS:
            continue
        tables.append(
            ScrapedTable(name=_caption_for(element, position), frame=frame, index=position)
        )
    return tables


def extract_article(html: str) -> ScrapedArticle:
    """Title plus visible body text — the fallback when a page has no tables at all."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    title_tag = soup.find("h1") or soup.find("title")
    title = _clean_cell(title_tag.get_text(" ")) if title_tag else ""
    paragraphs = [_clean_cell(p.get_text(" ")) for p in soup.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if p)
    return ScrapedArticle(title=title, text=text)
