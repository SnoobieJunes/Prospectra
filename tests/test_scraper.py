# 2026-07-14 (P5): Scraper tests. No network: the fetcher is a Protocol, so every test injects a
# canned page. What is proven here is the behaviour that matters — robots.txt is *obeyed* (not just
# parsed), the rate limiter waits per host, real tables are extracted with usable column names,
# page furniture is not, and the emitted CSVs are readable by DuckDB (which is the whole point:
# a scraped table must be an ordinary dataset).

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from prospectra.core.scraper import (
    LocalFileFetcher,
    Page,
    RateLimiter,
    RobotsCache,
    RobotsDisallowed,
    ScrapeResult,
    emit_tables,
    extract_article,
    extract_tables,
    parse_robots,
    scrape,
    slugify,
)
from prospectra.core.scraper.errors import NothingExtracted
from prospectra.core.scraper.fetcher import HttpFetcher

WIKI_PAGE = """
<html><head><title>List of countries by GDP</title></head>
<body>
<h1>List of countries by GDP</h1>
<p>This article lists countries by GDP.</p>
<table class="layout"><tr><td>nav</td></tr></table>
<table class="legend"><tr><td>&gt; $20 trillion</td><td>$10-20 trillion</td></tr></table>
<h2>Estimates</h2>
<table class="wikitable">
  <caption>GDP by country[1]</caption>
  <tr><th>Country</th><th>GDP (millions)[a]</th><th>Year</th></tr>
  <tr><td>United States</td><td>27720700</td><td>2024</td></tr>
  <tr><td>China</td><td>17794782</td><td>2024</td></tr>
  <tr><td>Germany</td><td>4525704</td><td>2024</td></tr>
</table>
<h2>Population</h2>
<table>
  <tr><th>Country</th><th>People</th></tr>
  <tr><td>United States</td><td>334914895</td></tr>
  <tr><td>China</td><td>1409670000</td></tr>
</table>
</body></html>
"""

ARTICLE_PAGE = """
<html><body><h1>Why ice cream sells</h1>
<script>tracking()</script>
<p>Warm weather brings buyers.</p><p>Schools out means families.</p></body></html>
"""


class FakeFetcher:
    """Serves canned HTML and records what was asked for."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.requested: list[str] = []

    def fetch(self, url: str) -> Page:
        self.requested.append(url)
        return Page(url=url, final_url=url, html=self.html)


# -- robots.txt ---------------------------------------------------------------------------------


def test_robots_disallow_is_obeyed():
    rules = parse_robots("User-agent: *\nDisallow: /private/\n")
    assert rules.allows("https://example.com/public/page", "ProspectraBot") is True
    assert rules.allows("https://example.com/private/secret", "ProspectraBot") is False


def test_robots_crawl_delay_is_read():
    rules = parse_robots("User-agent: *\nCrawl-delay: 10\nDisallow:\n")
    assert rules.crawl_delay("ProspectraBot") == 10.0


def test_missing_robots_txt_is_permissive():
    cache = RobotsCache(lambda _url: None)  # host serves no robots.txt
    rules = cache.rules_for("https://example.com/anything")
    assert rules.missing is True
    assert rules.allows("https://example.com/anything", "ProspectraBot") is True


def test_robots_is_fetched_once_per_host():
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "User-agent: *\nDisallow:\n"

    cache = RobotsCache(fetch)
    cache.rules_for("https://example.com/a")
    cache.rules_for("https://example.com/b")
    cache.rules_for("https://other.com/a")
    assert calls == ["https://example.com/robots.txt", "https://other.com/robots.txt"]


def test_http_fetcher_refuses_a_disallowed_url_without_fetching_it():
    """The refusal happens *before* the request — a disallowed page is never fetched."""
    fetcher = HttpFetcher()
    fetched: list[str] = []

    def robots(url: str) -> str:
        fetched.append(url)
        return "User-agent: *\nDisallow: /secret\n"

    fetcher._robots = RobotsCache(robots)
    with pytest.raises(RobotsDisallowed):
        fetcher.fetch("https://example.com/secret/page")
    assert fetched == ["https://example.com/robots.txt"]  # only robots.txt was ever requested
    fetcher.close()


# -- rate limiting -------------------------------------------------------------------------------


def test_rate_limiter_waits_between_requests_to_one_host():
    now = [0.0]
    slept: list[float] = []
    limiter = RateLimiter(1.0, clock=lambda: now[0], sleep=lambda s: slept.append(s))

    assert limiter.wait("https://a.com/1") == 0.0  # first request is immediate
    now[0] = 0.25
    waited = limiter.wait("https://a.com/2")
    assert waited == pytest.approx(0.75)  # 1.0s interval, 0.25s elapsed
    assert slept == [pytest.approx(0.75)]


def test_rate_limiter_is_per_host():
    now = [0.0]
    slept: list[float] = []
    limiter = RateLimiter(1.0, clock=lambda: now[0], sleep=lambda s: slept.append(s))
    limiter.wait("https://a.com/1")
    assert limiter.wait("https://b.com/1") == 0.0  # a different host waits for nothing
    assert slept == []


def test_crawl_delay_raises_the_interval_but_never_lowers_it():
    limiter = RateLimiter(1.0)
    limiter.set_host_interval("https://slow.com/x", 10.0)
    assert limiter.interval_for("https://slow.com/x") == 10.0
    limiter.set_host_interval("https://fast.com/x", 0.1)  # a site cannot ask us to go faster
    assert limiter.interval_for("https://fast.com/x") == 1.0


# -- parsing --------------------------------------------------------------------------------------


def test_extract_tables_finds_data_tables_and_skips_furniture():
    """The furniture floor is not theoretical: a live Wikipedia scrape emitted the page's map
    legend (1 row x 2 cols) as a dataset until the minimum-rows floor was raised to 2."""
    tables = extract_tables(WIKI_PAGE)
    assert len(tables) == 2  # the layout table and the one-row legend are not data
    assert tables[0].name == "GDP by country"  # caption wins, footnote marker stripped
    assert tables[1].name == "Population"  # no caption -> nearest heading


def test_extracted_columns_are_clean_and_usable_as_identifiers():
    gdp = extract_tables(WIKI_PAGE)[0]
    assert list(gdp.frame.columns) == ["Country", "GDP (millions)", "Year"]  # "[a]" is gone
    assert gdp.shape == (3, 3)


def test_headers_that_collide_only_after_cleaning_are_made_unique():
    """ "Total[a]" and "Total[b]" are distinct to pandas but identical once footnotes are stripped —
    two columns named "Total" would collide as SQL identifiers downstream."""
    html = (
        "<table><tr><th>Total[a]</th><th>Total[b]</th></tr>"
        "<tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
    )
    frame = extract_tables(html)[0].frame
    assert list(frame.columns) == ["Total", "Total_2"]


def test_extract_article_drops_scripts_and_keeps_text():
    article = extract_article(ARTICLE_PAGE)
    assert article.title == "Why ice cream sells"
    assert "tracking()" not in article.text
    assert "Warm weather brings buyers." in article.text


# -- emitting -------------------------------------------------------------------------------------


def test_emitted_csv_is_readable_by_duckdb(tmp_path: Path):
    """The point of the emitter: a scraped table becomes an ordinary dataset."""
    tables = extract_tables(WIKI_PAGE)
    files = emit_tables(tables, tmp_path)
    assert len(files) == 2

    con = duckdb.connect()
    sql = f"SELECT count(*) FROM read_csv_auto('{files[0].path.as_posix()}')"
    rows = con.execute(sql).fetchone()
    assert rows[0] == 3
    con.close()


def test_slugify_makes_a_filename_out_of_a_caption():
    assert slugify("GDP by country (millions)!") == "gdp_by_country_millions"
    assert slugify("") == "table"


# -- pipeline --------------------------------------------------------------------------------------


def test_scrape_writes_one_csv_per_table(tmp_path: Path):
    result = scrape("https://example.com/wiki/GDP", tmp_path, fetcher=FakeFetcher(WIKI_PAGE))
    assert isinstance(result, ScrapeResult)
    assert len(result.files) == 2
    assert all(f.path.exists() for f in result.files)
    assert "gdp" in result.files[0].path.name  # named from the page + caption


def test_scrape_falls_back_to_article_text_when_there_are_no_tables(tmp_path: Path):
    result = scrape("https://example.com/post", tmp_path, fetcher=FakeFetcher(ARTICLE_PAGE))
    assert result.files == []
    assert result.article_path is not None
    assert result.article_path.exists()


def test_tables_only_refuses_a_page_with_no_tables(tmp_path: Path):
    with pytest.raises(NothingExtracted):
        scrape(
            "https://example.com/post",
            tmp_path,
            fetcher=FakeFetcher(ARTICLE_PAGE),
            tables_only=True,
        )


def test_max_tables_caps_what_is_written(tmp_path: Path):
    result = scrape(
        "https://example.com/wiki/GDP", tmp_path, fetcher=FakeFetcher(WIKI_PAGE), max_tables=1
    )
    assert len(result.files) == 1


def test_local_file_fetcher_reads_a_saved_page(tmp_path: Path):
    saved = tmp_path / "page.html"
    saved.write_text(WIKI_PAGE, encoding="utf-8")
    page = LocalFileFetcher().fetch(str(saved))
    assert "GDP by country" in page.html
