# 2026-07-31 (P7): The core/http layer — the one send() path everything HTTP now goes through.
#
# The load-bearing assertions: send() NEVER raises (a 404 is a result to display), and empty
# params reach httpx as None, not {} — `params={}` tells httpx to strip the query string off a
# URL, which is exactly the bug that once made the Link paginator re-fetch page 1 forever.

from __future__ import annotations

import json

import httpx
import pytest

from prospectra.core.http import (
    Auth,
    HttpRequest,
    redact_headers,
    resolve_placeholders,
    send,
    to_curl,
)
from prospectra.core.scraper.rate_limit import RateLimiter


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# -- send() never raises ---------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 404, 500])
def test_any_status_is_a_result_not_an_exception(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "the body explains it"})

    response = send(HttpRequest(url="https://api.test/x"), transport=_transport(handler))
    assert response.status == status
    assert response.error == ""
    assert response.json == {"detail": "the body explains it"}
    assert response.ok is (status == 200)


def test_a_network_failure_sets_error_instead_of_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nobody home")

    response = send(HttpRequest(url="https://down.test/x"), transport=_transport(handler))
    assert response.status == 0
    assert "nobody home" in response.error
    assert response.ok is False


def test_a_non_json_body_still_arrives_as_text():
    response = send(
        HttpRequest(url="https://api.test/x"),
        transport=_transport(lambda r: httpx.Response(200, text="<html>hi</html>")),
    )
    assert response.json is None
    assert response.text == "<html>hi</html>"


# -- the params-or-None semantic (regression lock) -------------------------------------------


def test_empty_params_do_not_strip_the_urls_own_query_string():
    """params={} tells httpx to REPLACE the query string with nothing. The Link paginator once
    re-fetched page 1 forever because of exactly that. Locked here at the send() layer."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    send(HttpRequest(url="https://api.test/items?page=2"), transport=_transport(handler))
    assert seen == ["https://api.test/items?page=2"]  # the ?page=2 survived


def test_declared_params_are_merged_with_the_urls_query():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    send(
        HttpRequest(url="https://api.test/items", params={"per_page": "50"}),
        transport=_transport(handler),
    )
    assert seen == ["https://api.test/items?per_page=50"]


# -- headers, body, auth ---------------------------------------------------------------------


def test_typed_headers_and_json_body_are_transmitted():
    captured: dict[str, str] = {}
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update({k.lower(): v for k, v in request.headers.items()})
        bodies.append(request.read())
        return httpx.Response(200, json={"ok": True})

    send(
        HttpRequest(
            method="POST",
            url="https://api.test/things",
            headers={"X-Tenant": "acme"},
            body_kind="json",
            body='{"name": "shirt"}',
        ),
        transport=_transport(handler),
    )
    assert captured["x-tenant"] == "acme"
    assert captured["content-type"] == "application/json"
    assert json.loads(bodies[0]) == {"name": "shirt"}


def test_auth_secret_is_applied_at_send_time_never_stored():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json={})

    request = HttpRequest(url="https://api.test/x", auth=Auth(kind="bearer", secret_ref="kc:x"))
    send(request, "tok-123", transport=_transport(handler))
    assert captured["authorization"] == "Bearer tok-123"
    assert "tok-123" not in json.dumps(request.to_dict())  # the document never holds the secret


def test_rate_limiter_is_consulted_per_host():
    waits: list[float] = []
    fake_now = [0.0]
    limiter = RateLimiter(min_interval=1.0, clock=lambda: fake_now[0], sleep=waits.append)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    request = HttpRequest(url="https://api.test/x")
    send(request, transport=_transport(handler), limiter=limiter)
    send(request, transport=_transport(handler), limiter=limiter)
    assert waits == [1.0]  # the second hit on the same host had to wait


# -- redaction & placeholders ----------------------------------------------------------------


def test_redact_headers_masks_credentials_but_not_harmless_names():
    masked = redact_headers(
        {
            "Authorization": "Bearer tok",
            "X-API-Key": "k",
            "X-Auth-Token": "t",
            "Idempotency-Key": "abc",  # not a credential — must survive
            "Accept": "application/json",
        }
    )
    assert masked["Authorization"] == "***"
    assert masked["X-API-Key"] == "***"
    assert masked["X-Auth-Token"] == "***"
    assert masked["Idempotency-Key"] == "abc"
    assert masked["Accept"] == "application/json"


def test_secret_placeholders_resolve_without_touching_the_original():
    request = HttpRequest(
        url="https://api.test/x",
        headers={"X-API-Key": "{{secret:my-key}}"},
        body_kind="json",
        body='{"token": "{{secret:my-key}}"}',
    )
    resolved = resolve_placeholders(request, {"my-key": "s3cr3t"}.__getitem__)
    assert resolved.headers["X-API-Key"] == "s3cr3t"
    assert json.loads(resolved.body) == {"token": "s3cr3t"}
    assert request.headers["X-API-Key"] == "{{secret:my-key}}"  # the saved document is untouched


def test_to_curl_shows_the_request_shape_and_masks_the_credential():
    request = HttpRequest(
        method="POST",
        url="https://api.test/things",
        headers={"X-Tenant": "acme"},
        body_kind="json",
        body='{"a": 1}',
        auth=Auth(kind="bearer", secret_ref="kc:x"),
    )
    curl = to_curl(request)
    assert "curl" in curl and "-X POST" in curl
    assert "X-Tenant: acme" in curl
    assert "Authorization: ***" in curl
    assert '{"a": 1}' in curl
    assert "tok" not in curl  # to_curl is never handed the secret at all


# -- the document ----------------------------------------------------------------------------


def test_request_round_trips_and_refuses_a_newer_schema():
    request = HttpRequest(
        method="POST",
        url="https://api.test/x",
        headers={"X-A": "1"},
        params={"q": "shoes"},
        body_kind="json",
        body="{}",
        auth=Auth(kind="header", header="X-API-Key", secret_ref="kc:x"),
        timeout=10.0,
        follow_redirects=False,
    )
    assert HttpRequest.from_dict(request.to_dict()) == request
    with pytest.raises(ValueError, match="newer"):
        HttpRequest.from_dict({"request_schema": 99})


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (HttpRequest(url=""), "needs a URL"),
        (HttpRequest(url="ftp://x"), "http"),
        (HttpRequest(url="https://x", method="YEET"), "method"),
        (HttpRequest(url="https://x", body_kind="xml"), "body kind"),
        (HttpRequest(url="https://x", body_kind="none", body="oops"), "body kind is 'none'"),
        (HttpRequest(url="https://x", body_kind="json", body="{not json"), "does not parse"),
    ],
)
def test_validation_catches_the_mistake_before_anything_is_sent(request_, message):
    with pytest.raises(ValueError, match=message):
        request_.validate()


# -- file:// (the no-network CI path) --------------------------------------------------------


def test_a_file_url_is_served_from_disk(tmp_path):
    fixture = tmp_path / "response.json"
    fixture.write_text('{"items": [1, 2]}', encoding="utf-8")
    response = send(HttpRequest(url=fixture.as_uri()))
    assert response.ok and response.status == 200
    assert response.json == {"items": [1, 2]}


def test_a_missing_file_url_is_an_error_result():
    response = send(HttpRequest(url="file:///no/such/file.json"))
    assert response.ok is False
    assert response.error != ""
