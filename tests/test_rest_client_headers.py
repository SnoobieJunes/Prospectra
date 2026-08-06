# 2026-07-31 (P7): Proof that the dead-headers bug is dead. `RestMapping.headers` was declared,
# serialized, and deserialized since P6 — and never sent, because the old `_get` passed only the
# auth headers to httpx. This test failed against the P6 client; it passes now that `_get` goes
# through core/http's send(). Also covers the mapping's new v2 fields and the client-side limiter.

from __future__ import annotations

import httpx
import pytest

from prospectra.core.connectors.rest import RestClient, RestMapping
from prospectra.core.scraper.rate_limit import RateLimiter


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_mapping_headers_are_actually_transmitted():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json=[{"ok": 1}])

    mapping = RestMapping(url="https://api.test/x", headers={"X-Tenant": "acme"})
    RestClient(mapping, transport=_transport(handler)).records()
    assert captured["x-tenant"] == "acme"  # failed before P7: the header was declared, never sent


def test_a_mapping_body_rides_along_for_post_search_apis():
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        return httpx.Response(200, json={"rows": [{"n": 1}]})

    mapping = RestMapping(
        url="https://api.test/search",
        method="POST",
        body_kind="json",
        body='{"query": "everything"}',
        records_path="rows",
    )
    records, _report = RestClient(mapping, transport=_transport(handler)).records()
    assert [r["n"] for r in records] == [1]
    assert bodies[0] == b'{"query": "everything"}'


def test_the_mappings_rate_limit_paces_the_paginator():
    waits: list[float] = []
    fake_now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        rows = [{"id": page}] if page <= 2 else []
        return httpx.Response(200, json={"data": rows})

    from prospectra.core.connectors.rest.mapping import Pagination

    mapping = RestMapping(
        url="https://api.test/things",
        records_path="data",
        pagination=Pagination(kind="page", max_pages=10),
    )
    limiter = RateLimiter(min_interval=0.5, clock=lambda: fake_now[0], sleep=waits.append)
    RestClient(mapping, transport=_transport(handler), limiter=limiter).records()
    assert waits == [0.5, 0.5]  # pages 2 and 3 each waited for the host's interval


def test_mapping_v2_round_trips_and_v1_docs_still_load():
    mapping = RestMapping(
        url="https://api.test/x",
        headers={"X-Tenant": "acme"},
        body_kind="json",
        body='{"q": 1}',
        rate_limit_per_sec=2.0,
    )
    doc = mapping.to_dict()
    assert doc["mapping_schema"] == 2
    assert RestMapping.from_dict(doc) == mapping

    v1_doc = {"mapping_schema": 1, "url": "https://api.test/x", "name": "t"}
    v1 = RestMapping.from_dict(v1_doc)
    assert v1.body_kind == "none" and v1.rate_limit_per_sec == 0.0

    with pytest.raises(ValueError, match="newer"):
        RestMapping.from_dict({"mapping_schema": 3, "url": "https://x"})


def test_a_malformed_mapping_body_is_refused_at_validation():
    mapping = RestMapping(url="https://api.test/x", body_kind="json", body="{nope")
    with pytest.raises(ValueError, match="does not parse"):
        mapping.validate()
