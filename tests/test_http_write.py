# 2026-07-31 (P7): The REST write's rails — every one of them, against scripted endpoints.
# The assertions the plan names: dry_run issues ZERO requests; 5 consecutive failures trips the
# breaker; the row cap sets a note; 429 retries and 400 does not; the Idempotency-Key is stable.

from __future__ import annotations

import httpx
import pytest

from prospectra.core.flow import FlowGraph, FlowRunError, FlowRunner
from prospectra.core.http.request import Auth
from prospectra.core.http.write import WriteSpec, push_rows, write_failures_csv
from prospectra.core.scraper.rate_limit import RateLimiter


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _limiter() -> RateLimiter:
    return RateLimiter(min_interval=0.0, clock=lambda: 0.0, sleep=lambda s: None)


def spec(**overrides) -> WriteSpec:
    base = dict(
        url_template="https://api.test/products/{sku}",
        method="PUT",
        key_column="sku",
        rate_per_sec=0.0,
    )
    base.update(overrides)
    return WriteSpec(**base)


ROWS = [{"sku": f"A-{i}", "name": f"item {i}"} for i in range(10)]


# -- dry run: the resting state ---------------------------------------------------------------


def test_dry_run_issues_zero_requests():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    report = push_rows(spec(), ROWS, transport=_transport(handler))  # dry_run defaults True
    assert calls == []  # ZERO — this is the property everything else stands on
    assert report.dry_run is True
    assert report.attempted == 10 and report.written == 0
    assert any("0 requests sent" in note for note in report.notes)


def test_dry_run_still_catches_a_broken_template():
    report = push_rows(
        spec(url_template="https://api.test/products/{styleCode}"),  # rows have no styleCode
        ROWS,
        transport=_transport(lambda r: httpx.Response(200)),
    )
    assert report.failed == 10
    assert "styleCode" in report.failures[0].message


# -- live writes ------------------------------------------------------------------------------


def test_per_row_puts_land_and_carry_the_row_in_the_url():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json={"ok": True})

    report = push_rows(
        spec(), ROWS[:3], dry_run=False, transport=_transport(handler), limiter=_limiter()
    )
    assert report.written == 3 and report.failed == 0
    assert seen[0] == ("PUT", "https://api.test/products/A-0")


def test_a_400_is_attributed_to_its_specific_row_and_never_retried():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "A-1" in str(request.url):
            return httpx.Response(400, json={"error": "price is negative"})
        return httpx.Response(200)

    report = push_rows(
        spec(), ROWS[:3], dry_run=False, transport=_transport(handler), limiter=_limiter()
    )
    assert report.written == 2 and report.failed == 1
    failure = report.failures[0]
    assert failure.key == "A-1" and failure.status == 400
    assert "price is negative" in failure.message
    assert len([c for c in calls if "A-1" in c]) == 1  # a wrong request is not re-sent


def test_429_is_retried_honouring_retry_after():
    attempts: list[str] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200)

    report = push_rows(
        spec(),
        ROWS[:1],
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
        sleep=slept.append,
    )
    assert report.written == 1
    assert len(attempts) == 2  # once, 429, then again
    assert slept == [7.0]  # the server's Retry-After was honoured


def test_five_consecutive_failures_trip_the_breaker():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(400, json={"error": "no"})

    report = push_rows(
        spec(), ROWS, dry_run=False, transport=_transport(handler), limiter=_limiter()
    )
    assert report.failed == 5  # then it STOPPED — one bad mapping cannot fire 10,000 failing PUTs
    assert report.skipped == 5
    assert report.stopped_early is True
    assert any("consecutive failures" in note for note in report.notes)
    assert len(calls) == 5  # a 400 is never retried, so exactly five requests exist


def test_a_success_resets_the_consecutive_counter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400 if "A-0" not in str(request.url) else 200)

    rows = [
        {"sku": "A-1"},
        {"sku": "A-2"},
        {"sku": "A-0"},
        {"sku": "A-3"},
        {"sku": "A-4"},
        {"sku": "A-5"},
        {"sku": "A-6"},
    ]
    report = push_rows(
        spec(max_consecutive_failures=3),
        rows,
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
    )
    assert report.written == 1  # A-0 succeeded and reset the count
    assert report.stopped_early is True  # the tail of failures still tripped it


def test_the_row_cap_confesses_what_it_did_not_attempt():
    many = [{"sku": f"S-{i}"} for i in range(30)]
    report = push_rows(
        spec(max_rows=10),
        many,
        transport=_transport(lambda r: httpx.Response(200)),
    )
    assert report.attempted == 10
    assert report.skipped >= 20
    assert report.stopped_early is True
    assert any("cap" in note and "NOT attempted" in note for note in report.notes)


# -- POST + idempotency -----------------------------------------------------------------------


def test_post_requires_acknowledgement_before_anything_happens():
    with pytest.raises(ValueError, match="duplicates"):
        push_rows(
            spec(method="POST", url_template="https://api.test/products"),
            ROWS[:1],
            dry_run=False,
            transport=_transport(lambda r: httpx.Response(200)),
        )


def test_post_sends_a_stable_content_hash_idempotency_key():
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers.get("Idempotency-Key", ""))
        return httpx.Response(200)

    post_spec = spec(
        method="POST",
        url_template="https://api.test/products",
        post_acknowledged=True,
        key_column="",
    )
    push_rows(post_spec, ROWS[:1], dry_run=False, transport=_transport(handler), limiter=_limiter())
    push_rows(post_spec, ROWS[:1], dry_run=False, transport=_transport(handler), limiter=_limiter())
    assert keys[0] and keys[0] == keys[1]  # same content -> same key, across runs

    push_rows(
        post_spec,
        [{"sku": "B-9", "name": "other"}],
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
    )
    assert keys[2] != keys[0]  # different content -> different key


# -- pre-flight validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (dict(url_template=""), "needs a URL"),
        (dict(url_template="https://api.test/products"), "URL template naming the row"),
        (dict(key_column=""), "key column"),
        (dict(method="DELETE"), "must be one of"),
    ],
)
def test_a_broken_spec_dies_before_any_request(bad, message):
    with pytest.raises(ValueError, match=message):
        push_rows(spec(**bad), ROWS[:1], transport=_transport(lambda r: httpx.Response(200)))


# -- recovery ---------------------------------------------------------------------------------


def test_only_keys_reruns_just_the_named_rows():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    report = push_rows(
        spec(),
        ROWS,
        dry_run=False,
        transport=_transport(handler),
        limiter=_limiter(),
        only_keys=["A-3", "A-7"],
    )
    assert report.written == 2
    assert sorted(seen) == [
        "https://api.test/products/A-3",
        "https://api.test/products/A-7",
    ]
    assert any("targeted re-run" in note for note in report.notes)


def test_failures_export_to_csv_for_manual_recovery(tmp_path):
    report = push_rows(
        spec(),
        ROWS[:3],
        dry_run=False,
        transport=_transport(lambda r: httpx.Response(400, json={"error": "nope"})),
        limiter=_limiter(),
    )
    out = write_failures_csv(report, tmp_path / "failures.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "index,key,status,message"
    assert len(lines) == 1 + report.failed
    assert "A-0" in lines[1]


# -- the node inside a flow -------------------------------------------------------------------


def _rest_write_graph(tmp_path, transport):
    source = tmp_path / "rows.csv"
    source.write_text("sku,name\nA-1,shirt\nA-2,sock\n", encoding="utf-8")
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    sink = graph.add_node("output_rest", {"spec": spec().to_dict()})
    graph.add_edge(src, sink)
    graph.nodes[sink].node.transport = transport
    return graph


def test_the_node_is_destructive_and_the_runner_refuses_it(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    graph = _rest_write_graph(tmp_path, _transport(handler))
    with pytest.raises(FlowRunError, match="live writes"):
        FlowRunner().run(graph)
    assert calls == []


def test_the_node_pushes_flow_rows_when_allowed(tmp_path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    graph = _rest_write_graph(tmp_path, _transport(handler))
    results = FlowRunner().run(graph, allow_writes=True)
    assert results[0].written == 2
    assert "https://api.test/products/A-1" in seen


def test_the_node_dry_runs_through_the_runner_without_sending(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    graph = _rest_write_graph(tmp_path, _transport(handler))
    results = FlowRunner().run(graph, dry_run=True)
    assert results[0].dry_run is True and calls == []


def test_a_missing_url_template_dies_at_validate_ready_not_mid_write(tmp_path):
    graph = _rest_write_graph(tmp_path, None)
    sink = graph.output_nodes()[0]
    graph.nodes[sink].node.params["spec"] = WriteSpec(url_template="").to_dict()
    with pytest.raises(Exception, match="needs a URL"):
        graph.validate_ready(sink)  # the pre-flight seam — no request will ever exist


def test_write_spec_round_trips():
    original = spec(headers={"X-Tenant": "acme"}, auth=Auth(kind="bearer", secret_ref="kc:x"))
    assert WriteSpec.from_dict(original.to_dict()) == original
    with pytest.raises(ValueError, match="newer"):
        WriteSpec.from_dict({"write_spec_schema": 99})
