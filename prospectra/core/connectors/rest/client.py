# 2026-07-14 (P6): The REST client — walks a mapping's pagination and yields records.
#
# httpx is constructed with an injectable transport, which is how the whole paginator is tested
# against scripted APIs (page / offset / cursor / Link-header) with no network in CI.
#
# Two guards that exist because a paginator without them is a footgun aimed at someone else's API:
#   * max_pages and max_records are hard stops. An API that always returns a "next" cursor (they
#     exist) would otherwise loop forever.
#   * a page that returns zero records ends the walk, even if the API claims there is more.
# Both are reported to the caller, so "you got 10,000 of maybe more" is never mistaken for "that's
# all of it".

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from prospectra.core.connectors.base import ConnectorError
from prospectra.core.connectors.rest import paths
from prospectra.core.connectors.rest.mapping import RestMapping

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "Prospectra/0.1 (+https://github.com/SnoobieJunes/Prospectra)"


@dataclass
class FetchReport:
    """What actually happened — including the fact that the walk hit a cap, if it did."""

    pages: int = 0
    records: int = 0
    stopped_at_cap: bool = False
    notes: list[str] = field(default_factory=list)


class RestClient:
    def __init__(
        self,
        mapping: RestMapping,
        secret: str | None = None,
        *,
        transport: Any = None,  # httpx.BaseTransport — injected by tests
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        import httpx

        mapping.validate()
        self.mapping = mapping
        self._secret = secret
        self._last_headers: dict[str, str] = {}
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    # -- auth -----------------------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        auth = self.mapping.auth
        if auth.kind == "none" or self._secret is None:
            return {}
        if auth.kind == "bearer":
            return {"Authorization": f"Bearer {self._secret}"}
        if auth.kind == "basic":
            import base64

            token = base64.b64encode(f"{auth.user}:{self._secret}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        if auth.kind == "header":
            return {auth.header: self._secret}
        return {}

    def _auth_params(self) -> dict[str, str]:
        auth = self.mapping.auth
        if auth.kind == "query" and self._secret is not None:
            return {auth.param: self._secret}
        return {}

    def _requires_secret(self) -> bool:
        return self.mapping.auth.kind != "none"

    # -- fetching ---------------------------------------------------------------------------------

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        import httpx

        try:
            response = self._client.request(
                self.mapping.method,
                url,
                # `params={}` does not mean "no params" to httpx — it means "replace the query
                # string with nothing", which silently strips the ?page=2 off a next-link the
                # server just handed us. The Link paginator then re-fetched page 1 forever. Pass
                # None when there is nothing to add, so a URL's own query survives.
                params=params or None,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Could not reach {url}: {exc}") from exc
        if response.status_code in (401, 403):
            raise ConnectorError(
                f"{url} returned HTTP {response.status_code} — the API rejected the credential. "
                "Check the token in the mapping's auth settings."
            )
        if response.status_code >= 400:
            raise ConnectorError(f"{url} returned HTTP {response.status_code}")
        try:
            self._last_headers = dict(response.headers)
            return response.json()
        except ValueError as exc:
            raise ConnectorError(f"{url} did not return JSON") from exc

    def records(self) -> tuple[list[Any], FetchReport]:
        """Every record the mapping's pagination reaches, up to its caps."""
        if self._requires_secret() and not self._secret:
            raise ConnectorError(
                f"This mapping uses {self.mapping.auth.kind} auth but no credential was supplied. "
                "Add the API token (it is stored in your OS keychain, never in the project file)."
            )
        collected: list[Any] = []
        report = FetchReport()
        for page in self._pages():
            report.pages += 1
            found = paths.records_at(page, self.mapping.records_path)
            if not found:
                break  # an empty page ends the walk, whatever the API claims about "next"
            collected.extend(found)
            if len(collected) >= self.mapping.max_records:
                collected = collected[: self.mapping.max_records]
                report.stopped_at_cap = True
                report.notes.append(
                    f"Stopped at the {self.mapping.max_records:,}-record cap — the API may have "
                    "more."
                )
                break
        report.records = len(collected)
        if report.pages >= self.mapping.pagination.max_pages and not report.stopped_at_cap:
            report.notes.append(
                f"Stopped after {report.pages} pages (the mapping's page cap) — there may be more."
            )
            report.stopped_at_cap = True
        return collected, report

    def _pages(self) -> Iterator[Any]:
        """Yield each page's parsed body, walking whichever pagination the mapping declares."""
        mapping = self.mapping
        page_cfg = mapping.pagination
        base_params: dict[str, Any] = {**mapping.params, **self._auth_params()}

        if page_cfg.kind == "none":
            yield self._get(mapping.url, base_params)
            return

        if page_cfg.kind == "cursor":
            cursor: str | None = None
            for _ in range(page_cfg.max_pages):
                params = dict(base_params)
                params[page_cfg.size_param] = page_cfg.page_size
                if cursor:
                    params[page_cfg.cursor_param] = cursor
                body = self._get(mapping.url, params)
                yield body
                nxt = paths.resolve(body, page_cfg.next_path)
                if not nxt or not isinstance(nxt, str):
                    return
                cursor = nxt
            return

        if page_cfg.kind == "link":
            url: str | None = mapping.url
            params = dict(base_params)
            params[page_cfg.size_param] = page_cfg.page_size
            for _ in range(page_cfg.max_pages):
                if url is None:
                    return
                body = self._get(url, params)
                yield body
                url = self._next_link(body)
                params = {}  # the next URL already carries its own query string
            return

        # page / offset: a counter in the query string
        for index in range(page_cfg.max_pages):
            params = dict(base_params)
            params[page_cfg.size_param] = page_cfg.page_size
            if page_cfg.kind == "page":
                params[page_cfg.page_param] = page_cfg.start + index
            else:
                params[page_cfg.offset_param] = index * page_cfg.page_size
            yield self._get(mapping.url, params)

    def _next_link(self, body: Any) -> str | None:
        """RFC 5988 `Link: <…>; rel="next"`, or a URL named by the mapping's next_path."""
        if self.mapping.pagination.next_path:
            found = paths.resolve(body, self.mapping.pagination.next_path)
            return found if isinstance(found, str) and found else None
        link = self._last_headers.get("link") or self._last_headers.get("Link", "")
        for part in link.split(","):
            if 'rel="next"' in part:
                start, end = part.find("<"), part.find(">")
                if 0 <= start < end:
                    return part[start + 1 : end]
        return None

    def close(self) -> None:
        self._client.close()
