# 2026-07-31 (P7): One function actually performs HTTP for the whole app. The playground, the REST
# connector's paginator, and the P7 write path all go through `send()`, so the rules live in one
# place: auth is applied here, rate limiting is applied here, and the response is *returned* —
# never raised — because a 404 with a helpful JSON error body is a result to display.
#
# The transport is injectable (httpx.MockTransport in tests), and `file://` URLs are served from
# disk — that is how CI exercises the entire send path with no network, the same convention the
# scraper established.

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from prospectra.core.http.request import Auth, HttpRequest, HttpResponse
from prospectra.core.scraper.rate_limit import RateLimiter

USER_AGENT = "Prospectra/0.1 (+https://github.com/SnoobieJunes/Prospectra)"

_BODY_CONTENT_TYPES = {
    "json": "application/json",
    "text": "text/plain; charset=utf-8",
    "form": "application/x-www-form-urlencoded",
}


def auth_headers(auth: Auth, secret: str | None) -> dict[str, str]:
    """The headers an auth style adds. No secret -> no headers (never a broken half-credential)."""
    if auth.kind == "none" or not secret:
        return {}
    if auth.kind == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth.kind == "basic":
        token = base64.b64encode(f"{auth.user}:{secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    if auth.kind == "header":
        return {auth.header: secret}
    return {}


def auth_params(auth: Auth, secret: str | None) -> dict[str, str]:
    if auth.kind == "query" and secret:
        return {auth.param: secret}
    return {}


def send(
    request: HttpRequest,
    secret: str | None = None,
    *,
    transport: Any = None,  # httpx.BaseTransport — injected by tests
    limiter: RateLimiter | None = None,
) -> HttpResponse:
    """Execute the request and return what happened — always, even when nothing came back.

    Network failure is an `HttpResponse` with `.error` set, not an exception: the playground shows
    it in the response pane, and callers that need an exception (the REST connector) raise their
    own from it.
    """
    request.validate()

    if request.url.lower().startswith("file://"):
        return _send_file(request)

    import httpx

    headers = {"User-Agent": USER_AGENT, **request.headers}
    headers.update(auth_headers(request.auth, secret))
    content_type = _BODY_CONTENT_TYPES.get(request.body_kind)
    if content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = content_type
    params = {**request.params, **auth_params(request.auth, secret)}

    if limiter is not None:
        limiter.wait(request.url)

    # 2026-08-05: MERGE the params into the URL's own query rather than handing them to httpx.
    # httpx REPLACES the query string when `params` is given — it does not merge — so any
    # non-empty params silently deleted a URL's own `?page=2`. Passing `params or None` only
    # covered the empty case; the moment query auth put a key in `params`, the Link paginator
    # re-fetched page 1 forever (the exact bug the P6 comment below was written to prevent) and
    # a `?q=` typed in the playground vanished. `copy_merge_params` keeps both, and `to_curl`
    # renders the same merged URL, so the preview matches the wire.
    url = httpx.URL(request.url)
    if params:
        url = url.copy_merge_params(params)

    started = time.monotonic()
    try:
        with httpx.Client(
            transport=transport,
            timeout=request.timeout,
            follow_redirects=request.follow_redirects,
        ) as client:
            response = client.request(
                request.method.upper(),
                url,
                headers=headers,
                content=request.body.encode("utf-8") if request.body_kind != "none" else None,
            )
    except httpx.HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        return HttpResponse(error=f"{type(exc).__name__}: {exc}", elapsed_ms=elapsed)

    elapsed = (time.monotonic() - started) * 1000.0
    return HttpResponse(
        status=response.status_code,
        reason=response.reason_phrase,
        headers=dict(response.headers),
        text=response.text,
        json=_parse_json(response.text),
        elapsed_ms=elapsed,
        size_bytes=len(response.content),
    )


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _send_file(request: HttpRequest) -> HttpResponse:
    """Serve a file:// URL from disk — the no-network path CI uses to exercise `send()`."""
    if request.method.upper() != "GET":
        return HttpResponse(error=f"file:// URLs only support GET, not {request.method}")
    path = url2pathname(urlparse(request.url).path)
    started = time.monotonic()
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    # 2026-08-05: ValueError too — a non-UTF-8 body raised UnicodeDecodeError straight through
    # `send()`, breaking the never-raises contract every caller is written against.
    except (OSError, ValueError) as exc:
        return HttpResponse(error=f"Could not read {path}: {exc}")
    elapsed = (time.monotonic() - started) * 1000.0
    return HttpResponse(
        status=200,
        reason="OK",
        text=text,
        json=_parse_json(text),
        elapsed_ms=elapsed,
        size_bytes=len(text.encode("utf-8")),
    )
