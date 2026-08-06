# 2026-07-31 (P7): The REST write — the most dangerous thing in this app. A non-technical user,
# a wrong mapping and a live endpoint is an unrecoverable event on someone else's system, so the
# rails are not optional:
#
#   * dry_run defaults to True and issues ZERO requests — rehearsal is the resting state;
#   * per_row is the default mode, because a 400 attributable to a SPECIFIC row is the product
#     for a non-technical user ("row 37, styleCode AB1234, was rejected: price is negative");
#   * a consecutive-failure circuit breaker (5) — one bad mapping must not fire 10,000 failing
#     PUTs at someone's API; a hard row cap (1,000) that CONFESSES when it truncates;
#   * retry only on 429/5xx, honouring Retry-After. NEVER on other 4xx — the request is wrong,
#     and re-sending a wrong request is hammering, not persistence;
#   * POST sends a content-hash Idempotency-Key. Honoured by Stripe-class APIs, ignored by most —
#     which is why POST also requires explicit acknowledgement that duplicates are possible.
#
# `WriteReport.failures` is NOT a resume log; real resumability needs durable per-row outcomes.
# Recovery is manual and stated as such: export the failures to CSV, fix, re-run with only_keys.

from __future__ import annotations

import csv
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from prospectra.core.http.request import Auth, HttpRequest
from prospectra.core.http.send import send
from prospectra.core.report import RowFailure, WriteReport
from prospectra.core.scraper.rate_limit import RateLimiter

WRITE_SPEC_SCHEMA = 1

WRITE_METHODS = ("PUT", "PATCH", "POST")
WRITE_MODES = ("per_row", "batch")

DEFAULT_MAX_ROWS = 1_000
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
MAX_RETRIES = 3  # per request, and only ever for 429/5xx
# 2026-08-05: a server-supplied Retry-After is honoured but CAPPED. Unbounded, an endpoint
# answering "Retry-After: 86400" parked the flow runner for three days per attempt, with nothing
# in the report to say why.
MAX_RETRY_AFTER_SECONDS = 60.0


@dataclass
class WriteSpec:
    """Where rows go and under which rails. Serializable; the secret stays in the keychain."""

    url_template: str = ""  # per_row: ".../products/{styleCode}"; batch: the collection URL
    method: str = "PUT"
    key_column: str = ""  # the column that identifies a row (fills the template, names failures)
    body_kind: str = "json"
    mode: str = "per_row"
    chunk: int = 100  # batch mode: rows per request
    max_rows: int = DEFAULT_MAX_ROWS
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES
    rate_per_sec: float = 1.0
    idempotency: bool = True
    post_acknowledged: bool = False  # POST may duplicate on retry; the user must say they know
    auth: Auth = field(default_factory=Auth)
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0

    def validate(self) -> None:
        """Everything that can be wrong BEFORE any request goes out — the pre-flight seam."""
        if not self.url_template.strip():
            raise ValueError("the write needs a URL template")
        if not self.url_template.lower().startswith(("http://", "https://")):
            raise ValueError("the URL template must be http(s)")
        if self.method.upper() not in WRITE_METHODS:
            raise ValueError(f"write method must be one of {', '.join(WRITE_METHODS)}")
        if self.mode not in WRITE_MODES:
            raise ValueError(f"write mode must be one of {', '.join(WRITE_MODES)}")
        if self.method.upper() in ("PUT", "PATCH"):
            if not self.key_column.strip():
                raise ValueError(
                    f"{self.method} needs a key column — it is what makes a failure "
                    "attributable to a specific row"
                )
            if "{" not in self.url_template:
                raise ValueError(
                    f"{self.method} needs a URL template naming the row, "
                    "e.g. https://api.example.com/products/{styleCode}"
                )
        if self.method.upper() == "POST" and not self.post_acknowledged:
            raise ValueError(
                "POST can create duplicates if a retry lands twice (the Idempotency-Key is "
                "only honoured by some APIs) — acknowledge that to proceed"
            )
        if self.chunk < 1:
            raise ValueError("batch size must be at least 1")
        if self.max_rows < 1:
            raise ValueError("the row cap must be at least 1")
        self.auth.validate()

    # -- persistence ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_spec_schema": WRITE_SPEC_SCHEMA,
            "url_template": self.url_template,
            "method": self.method,
            "key_column": self.key_column,
            "body_kind": self.body_kind,
            "mode": self.mode,
            "chunk": self.chunk,
            "max_rows": self.max_rows,
            "max_consecutive_failures": self.max_consecutive_failures,
            "rate_per_sec": self.rate_per_sec,
            "idempotency": self.idempotency,
            "post_acknowledged": self.post_acknowledged,
            "auth": self.auth.to_dict(),
            "headers": dict(self.headers),
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> WriteSpec:
        version = int(doc.get("write_spec_schema", WRITE_SPEC_SCHEMA))
        if version > WRITE_SPEC_SCHEMA:
            raise ValueError(
                f"Write spec v{version} is newer than this app supports (v{WRITE_SPEC_SCHEMA})"
            )
        return cls(
            url_template=str(doc.get("url_template", "")),
            method=str(doc.get("method", "PUT")),
            key_column=str(doc.get("key_column", "")),
            body_kind=str(doc.get("body_kind", "json")),
            mode=str(doc.get("mode", "per_row")),
            chunk=int(doc.get("chunk", 100)),
            max_rows=int(doc.get("max_rows", DEFAULT_MAX_ROWS)),
            max_consecutive_failures=int(
                doc.get("max_consecutive_failures", DEFAULT_MAX_CONSECUTIVE_FAILURES)
            ),
            rate_per_sec=float(doc.get("rate_per_sec", 1.0)),
            idempotency=bool(doc.get("idempotency", True)),
            post_acknowledged=bool(doc.get("post_acknowledged", False)),
            auth=Auth.from_dict(doc.get("auth", {})),
            headers={str(k): str(v) for k, v in dict(doc.get("headers", {})).items()},
            timeout=float(doc.get("timeout", 30.0)),
        )


def _render_url(template: str, row: dict[str, Any]) -> str:
    """Fill {column} placeholders with URL-quoted row values; a missing column raises."""
    url = template
    for key, value in row.items():
        url = url.replace("{" + str(key) + "}", quote(str(value), safe=""))
    # 2026-08-05: any leftover brace is a fault. The old `"{" in url and "}" in url` passed a
    # template like ".../{id}?odd={" straight to the wire once a `}` existed anywhere.
    if "{" in url or "}" in url:
        start = url.find("{")
        end = url.find("}", start) if start >= 0 else -1
        wanted = url[start + 1 : end] if 0 <= start < end else url[max(start, 0) :]
        raise ValueError(
            f"the URL template has an unfilled placeholder {wanted!r} — no such column in the row"
        )
    return url


def _idempotency_key(body: str) -> str:
    """Content-hash: the same row content always carries the same key, across runs and retries."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def push_rows(
    spec: WriteSpec,
    rows: list[dict[str, Any]],
    secret: str | None = None,
    *,
    dry_run: bool = True,
    transport: Any = None,
    limiter: RateLimiter | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    only_keys: list[str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WriteReport:
    """Push mapped rows to the spec's endpoint — under every rail described above.

    `only_keys` is the manual-recovery path: re-run just the rows whose key column matches
    (typically the keys exported from a previous report's failures).
    """
    spec.validate()
    report = WriteReport(dry_run=dry_run)

    if only_keys is not None:
        wanted = {str(k) for k in only_keys}
        before = len(rows)
        rows = [r for r in rows if str(r.get(spec.key_column, "")) in wanted]
        report.notes.append(f"targeted re-run: {len(rows)} of {before} row(s) match the given keys")

    if len(rows) > spec.max_rows:
        report.notes.append(
            f"stopped at the {spec.max_rows:,}-row cap — {len(rows) - spec.max_rows:,} "
            "row(s) were NOT attempted; raise the cap deliberately if you mean it"
        )
        report.skipped += len(rows) - spec.max_rows
        report.stopped_early = True
        rows = rows[: spec.max_rows]

    if dry_run:
        # ZERO requests. Validate what CAN be validated offline: keys present, templates fill.
        for index, row in enumerate(rows):
            report.attempted += 1
            try:
                if spec.mode == "per_row":
                    _render_url(spec.url_template, row)
                if spec.key_column and spec.key_column not in row:
                    raise ValueError(f"row has no {spec.key_column!r} column")
            except ValueError as exc:
                report.failed += 1
                report.failures.append(
                    RowFailure(index, str(row.get(spec.key_column, "")), 0, str(exc))
                )
        report.skipped += report.attempted - report.failed
        report.notes.append(f"dry run: {report.attempted:,} row(s) rehearsed, 0 requests sent")
        return report

    if limiter is None:
        limiter = RateLimiter(min_interval=1.0 / spec.rate_per_sec if spec.rate_per_sec > 0 else 0)

    batches: list[tuple[int, list[dict[str, Any]]]]
    if spec.mode == "batch":
        batches = [
            (start, rows[start : start + spec.chunk]) for start in range(0, len(rows), spec.chunk)
        ]
    else:
        batches = [(index, [row]) for index, row in enumerate(rows)]

    consecutive = 0
    for done, (start_index, batch) in enumerate(batches):
        if consecutive >= spec.max_consecutive_failures:
            remaining = sum(len(b) for _s, b in batches[done:])
            report.skipped += remaining
            report.stopped_early = True
            report.notes.append(
                f"stopped after {consecutive} consecutive failures — {remaining} row(s) were "
                "not attempted. Check the mapping/endpoint before re-running (resume is "
                "manual: export the failures and re-run with only those keys)."
            )
            break
        succeeded = _push_batch(spec, batch, start_index, secret, transport, limiter, sleep, report)
        consecutive = 0 if succeeded else consecutive + 1
        if on_progress is not None:
            on_progress(min(start_index + len(batch), len(rows)), len(rows))
    return report


def _push_batch(
    spec: WriteSpec,
    batch: list[dict[str, Any]],
    start_index: int,
    secret: str | None,
    transport: Any,
    limiter: RateLimiter,
    sleep: Callable[[float], None],
    report: WriteReport,
) -> bool:
    """One request (one row in per_row mode). Returns True when the rows landed."""
    report.attempted += len(batch)

    # 2026-08-05: EVERY row in a failed batch gets its own RowFailure. One failure per batch meant
    # the failures CSV — the documented recovery path — recorded a single key per chunk, so a
    # default chunk of 100 lost 99 keys and a targeted re-run silently skipped them.
    def fail(status: int, message: str) -> bool:
        report.failed += len(batch)
        for offset, row in enumerate(batch):
            report.failures.append(
                RowFailure(start_index + offset, str(row.get(spec.key_column, "")), status, message)
            )
        return False

    try:
        if spec.mode == "per_row":
            url = _render_url(spec.url_template, batch[0])
            body = _encode_body(spec.body_kind, batch[0])
        else:
            url = spec.url_template
            body = _encode_body(spec.body_kind, batch)
    except ValueError as exc:
        return fail(0, str(exc))

    headers = dict(spec.headers)
    if spec.method.upper() == "POST" and spec.idempotency:
        headers["Idempotency-Key"] = _idempotency_key(body)

    request = HttpRequest(
        method=spec.method.upper(),
        url=url,
        headers=headers,
        body_kind=spec.body_kind,  # was hardcoded "json", making the declared kind write-only
        body=body,
        auth=spec.auth,
        timeout=spec.timeout,
        # 2026-08-05: a write NEVER follows redirects. httpx rewrites POST->GET on 301/302/303,
        # so a redirecting endpoint (an http:// typo is the usual way) silently dropped the body
        # and the run reported those rows WRITTEN. False write success is the failure this whole
        # module exists to prevent.
        follow_redirects=False,
    )

    for attempt in range(MAX_RETRIES + 1):
        response = send(request, secret, transport=transport, limiter=limiter)
        if response.error:
            status, message = 0, response.error
        elif 300 <= response.status < 400:
            location = response.headers.get("location") or response.headers.get("Location") or ""
            return fail(
                response.status,
                f"the endpoint redirected to {location or 'another address'} — writes do not "
                "follow redirects (the body would be dropped). Point the URL template at the "
                "final address.",
            )
        elif response.ok:
            report.written += len(batch)
            return True
        else:
            status, message = response.status, _failure_message(response)
        # Retry ONLY on 429/5xx (and transport failures), honouring Retry-After. A 400 is a
        # wrong request; re-sending it is hammering, not persistence.
        retryable = status == 0 or status == 429 or status >= 500
        if not retryable or attempt == MAX_RETRIES:
            return fail(status, message)
        retry_after, capped = _retry_after_seconds(response.headers)
        if capped:
            report.notes.append(
                f"the endpoint asked for a longer wait than the {MAX_RETRY_AFTER_SECONDS:.0f}s "
                "cap; waited the cap instead"
            )
        if retry_after > 0:
            sleep(retry_after)
    return False  # unreachable; the loop always returns


def _encode_body(body_kind: str, payload: Any) -> str:
    """Serialize a row (or batch) in the spec's declared body kind."""
    if body_kind == "form":
        if not isinstance(payload, dict):
            raise ValueError("form bodies send one row at a time — use per_row mode")
        return urlencode({str(k): "" if v is None else str(v) for k, v in payload.items()})
    if body_kind == "text":
        return str(payload)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _failure_message(response: Any) -> str:
    text = response.text.strip().replace("\n", " ")
    return f"{response.reason}: {text[:200]}" if text else response.reason


def _retry_after_seconds(headers: dict[str, str]) -> tuple[float, bool]:
    """(seconds to wait, whether the server's value was capped)."""
    raw = headers.get("retry-after") or headers.get("Retry-After") or ""
    try:
        asked = max(0.0, float(raw))
    except ValueError:
        return 0.0, False  # an HTTP-date Retry-After is rare; waiting 0s beats crashing on it
    return min(asked, MAX_RETRY_AFTER_SECONDS), asked > MAX_RETRY_AFTER_SECONDS


def write_failures_csv(report: WriteReport, path: Path | str) -> Path:
    """The manual-recovery artifact: every failed row's index, key, status, and reason."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as handle:  # newline="" — Windows rule
        writer = csv.writer(handle)
        writer.writerow(["index", "key", "status", "message"])
        for failure in report.failures:
            writer.writerow([failure.index, failure.key, failure.status, failure.message])
    return out
