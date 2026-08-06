# 2026-08-05: Locks for the defects an adversarial review of P7 found. Each test here failed
# against the code as originally written; several cover claims the original tests *asserted* but
# only in the narrow case that happened to still hold.

from __future__ import annotations

import subprocess
import sys

import httpx
import pytest

from prospectra.core.connectors.rest import RestClient, RestMapping
from prospectra.core.connectors.rest.mapping import Auth as RestAuth
from prospectra.core.connectors.rest.mapping import Pagination
from prospectra.core.http import HttpRequest, send, to_curl
from prospectra.core.http.write import (
    MAX_RETRY_AFTER_SECONDS,
    WriteSpec,
    push_rows,
)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _limiter():
    from prospectra.core.scraper.rate_limit import RateLimiter

    return RateLimiter(min_interval=0.0, clock=lambda: 0.0, sleep=lambda s: None)


# -- the query-string regression ---------------------------------------------------------------


def test_declared_params_merge_with_the_urls_own_query_instead_of_replacing_it():
    """httpx REPLACES the query when given params. The old code only guarded the empty case."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    send(
        HttpRequest(url="https://api.test/items?q=shoes", params={"page": "2"}),
        transport=_transport(handler),
    )
    assert "q=shoes" in seen[0] and "page=2" in seen[0]


def test_link_pagination_with_query_auth_still_follows_the_servers_next_link():
    """The regression: auth moved into send(), params became non-empty, and the server's
    ?page=2 was deleted — so page 1 came back forever and the duplicates were returned as data."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json=[{"i": "p1"}],
                headers={"Link": '<https://api.test/items?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"i": "p2"}])

    mapping = RestMapping(
        url="https://api.test/items",
        records_path="",
        pagination=Pagination(kind="link", max_pages=4),
        auth=RestAuth(kind="query", param="api_key"),
    )
    records, _report = RestClient(mapping, "K", transport=_transport(handler)).records()
    assert [r["i"] for r in records] == ["p1", "p2"]
    assert "api_key=K" in seen[1] and "page=2" in seen[1]  # auth AND the next-link survive


# -- send() never raises -----------------------------------------------------------------------


def test_a_non_utf8_file_body_is_an_error_result_not_an_exception(tmp_path):
    binary = tmp_path / "body.bin"
    binary.write_bytes(b"\xff\xfe\x00not utf-8")
    response = send(HttpRequest(url=binary.as_uri()))
    assert response.ok is False and response.error != ""


# -- curl redaction ----------------------------------------------------------------------------


def test_to_curl_masks_a_credential_typed_into_a_query_parameter():
    curl = to_curl(HttpRequest(url="https://api.test/x", params={"api_key": "sk-live-SUPERSECRET"}))
    assert "sk-live-SUPERSECRET" not in curl
    assert "api_key=%2A%2A%2A" in curl or "api_key=***" in curl


# -- the write path ----------------------------------------------------------------------------


def _spec(**overrides) -> WriteSpec:
    base = dict(
        url_template="https://api.test/p/{sku}",
        method="PUT",
        key_column="sku",
        rate_per_sec=0.0,
    )
    base.update(overrides)
    return WriteSpec(**base)


def test_a_redirected_write_is_a_failure_not_a_silent_success():
    """httpx rewrites POST->GET on 302; the body vanishes. That must never read as 'written'."""
    wire: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wire.append((request.method, len(request.read())))
        if request.url.scheme == "http":
            return httpx.Response(302, headers={"Location": "https://api.test/create"})
        return httpx.Response(200, json={"ok": True})

    report = push_rows(
        _spec(
            url_template="http://api.test/create",
            method="POST",
            key_column="",
            mode="batch",
            chunk=2,
            post_acknowledged=True,
        ),
        [{"sku": "A"}, {"sku": "B"}],
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
    )
    assert report.written == 0
    assert report.failed == 2
    assert "redirect" in report.failures[0].message
    assert [m for m, _ in wire] == ["POST"]  # it never became a GET


def test_every_row_of_a_failed_batch_gets_its_own_key():
    report = push_rows(
        _spec(
            method="POST",
            url_template="https://api.test/c",
            mode="batch",
            chunk=3,
            post_acknowledged=True,
        ),
        [{"sku": f"r{i}"} for i in range(3)],
        dry_run=False,
        transport=_transport(lambda r: httpx.Response(400, json={"e": "no"})),
        limiter=_limiter(),
    )
    assert report.failed == 3
    assert [f.key for f in report.failures] == ["r0", "r1", "r2"]


def test_retry_after_is_capped_and_the_cap_is_confessed():
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "86400"})
        return httpx.Response(200)

    report = push_rows(
        _spec(),
        [{"sku": "A"}],
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
        sleep=slept.append,
    )
    assert slept == [MAX_RETRY_AFTER_SECONDS]
    assert any("cap" in note for note in report.notes)
    assert report.written == 1


def test_the_declared_body_kind_is_actually_used():
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        return httpx.Response(200)

    push_rows(
        _spec(body_kind="form"),
        [{"sku": "A-1", "name": "shirt"}],
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
    )
    assert bodies[0] == b"sku=A-1&name=shirt"  # was hardcoded JSON regardless of the spec


def test_an_unfilled_placeholder_is_refused_even_with_a_stray_brace():
    report = push_rows(
        _spec(url_template="https://api.test/p/{sku}?odd={"),
        [{"sku": "A"}],
        dry_run=False,
        transport=_transport(lambda r: httpx.Response(200)),
        limiter=_limiter(),
    )
    assert report.failed == 1 and "placeholder" in report.failures[0].message


# -- layering ----------------------------------------------------------------------------------


def test_core_http_write_imports_on_a_cold_interpreter():
    """It used to be a circular import; the suite hid it by importing core.flow first."""
    result = subprocess.run(
        [sys.executable, "-c", "import prospectra.core.http.write"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["prospectra.core.http", "prospectra.core.mapping"])
def test_the_lower_layers_import_without_the_flow_engine(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
