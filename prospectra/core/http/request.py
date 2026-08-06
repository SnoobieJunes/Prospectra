# 2026-07-31 (P7): The request/response documents for the API playground — one HTTP exchange as
# data, not code (the ChartSpec pattern applied to HTTP).
#
# `HttpRequest` round-trips through JSON so a playground request can be saved into the project
# file, shared, and replayed from the CLI (`prospectra api-send`). The secret NEVER lives in it:
# `auth.secret_ref` names an OS-keychain entry, and `{{secret:<ref>}}` placeholders in headers,
# params, or the body are resolved at send time — the document itself stays safe to email.
#
# `Auth` lives here (not in the REST connector) because auth is an HTTP concern: the connector's
# mapping and the playground and the P7 write path all share the same five kinds. The REST mapping
# module re-exports it, so nothing that imported it from there breaks.

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

REQUEST_SCHEMA = 1

AUTH_KINDS = ("none", "bearer", "basic", "header", "query")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
BODY_KINDS = ("none", "json", "text", "form")

DEFAULT_TIMEOUT = 30.0

# Header names that carry credentials. Matched case-insensitively; the *contains* set catches the
# vendor variants (X-API-Key, X-Auth-Token, …) without masking harmless names like Idempotency-Key.
_SENSITIVE_EXACT = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie"})
# 2026-08-05: matched against the name with separators stripped, so api_key / api-key / apiKey /
# X-Api-Key all hit the same rule. Matching the literal spellings missed the underscore form —
# which is the one query parameters actually use.
_SENSITIVE_CONTAINS = ("apikey", "token", "secret", "password", "passwd", "credential", "auth")

MASK = "***"

_PLACEHOLDER = re.compile(r"\{\{\s*secret:([^{}]+?)\s*\}\}")


@dataclass
class Auth:
    kind: str = "none"
    secret_ref: str = ""  # keychain entry name — NEVER the secret itself
    user: str = ""  # basic auth username (not a secret)
    header: str = ""  # for kind="header": the header name, e.g. "X-API-Key"
    param: str = ""  # for kind="query": the query parameter name, e.g. "api_key"

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "secret_ref": self.secret_ref,
            "user": self.user,
            "header": self.header,
            "param": self.param,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Auth:
        return cls(
            kind=str(doc.get("kind", "none")),
            secret_ref=str(doc.get("secret_ref", "")),
            user=str(doc.get("user", "")),
            header=str(doc.get("header", "")),
            param=str(doc.get("param", "")),
        )

    def validate(self) -> None:
        if self.kind not in AUTH_KINDS:
            raise ValueError(f"unknown auth kind {self.kind!r}")
        if self.kind == "header" and not self.header:
            raise ValueError("header auth needs the header's name")
        if self.kind == "query" and not self.param:
            raise ValueError("query auth needs the parameter's name")


@dataclass
class HttpRequest:
    """One HTTP request, serializable. The playground edits one of these; `send()` executes it."""

    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    body_kind: str = "none"
    body: str = ""
    auth: Auth = field(default_factory=Auth)
    timeout: float = DEFAULT_TIMEOUT
    follow_redirects: bool = True

    def validate(self) -> None:
        if not self.url.strip():
            raise ValueError("the request needs a URL")
        # file:// is deliberately allowed: it is how CI and offline fixtures exercise the whole
        # send path with no network (the same convention the scraper uses).
        if not self.url.lower().startswith(("http://", "https://", "file://")):
            raise ValueError("the URL must be http(s) or file://")
        if self.method.upper() not in METHODS:
            raise ValueError(f"unknown HTTP method {self.method!r}")
        if self.body_kind not in BODY_KINDS:
            raise ValueError(
                f"unknown body kind {self.body_kind!r} (have: {', '.join(BODY_KINDS)})"
            )
        if self.body_kind == "none" and self.body.strip():
            # Refusing beats silently not sending what the user typed.
            raise ValueError(
                "a body was provided but the body kind is 'none' — pick json/text/form"
            )
        if self.body_kind == "json" and self.body.strip():
            try:
                json.loads(self.body)
            except ValueError as exc:
                raise ValueError(f"the JSON body does not parse: {exc}") from exc
        self.auth.validate()

    # -- persistence ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_schema": REQUEST_SCHEMA,
            "method": self.method,
            "url": self.url,
            "headers": dict(self.headers),
            "params": dict(self.params),
            "body_kind": self.body_kind,
            "body": self.body,
            "auth": self.auth.to_dict(),
            "timeout": self.timeout,
            "follow_redirects": self.follow_redirects,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> HttpRequest:
        version = int(doc.get("request_schema", REQUEST_SCHEMA))
        if version > REQUEST_SCHEMA:
            raise ValueError(
                f"Request schema v{version} is newer than this app supports (v{REQUEST_SCHEMA})"
            )
        return cls(
            method=str(doc.get("method", "GET")),
            url=str(doc.get("url", "")),
            headers={str(k): str(v) for k, v in dict(doc.get("headers", {})).items()},
            params={str(k): str(v) for k, v in dict(doc.get("params", {})).items()},
            body_kind=str(doc.get("body_kind", "none")),
            body=str(doc.get("body", "")),
            auth=Auth.from_dict(doc.get("auth", {})),
            timeout=float(doc.get("timeout", DEFAULT_TIMEOUT)),
            follow_redirects=bool(doc.get("follow_redirects", True)),
        )


@dataclass
class HttpResponse:
    """What came back — including "nothing came back". `send()` returns one of these for every
    outcome: a 404 with a helpful JSON error body is a result to display, not an exception."""

    status: int = 0
    reason: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    json: Any = None  # parsed body when it parses; None otherwise (see `text` for the raw bytes)
    elapsed_ms: float = 0.0
    size_bytes: int = 0
    error: str = ""  # non-empty = the request never completed (DNS, refused, timeout…)

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 400


def is_sensitive_name(name: str) -> bool:
    """Does this header/parameter name look like it carries a credential?"""
    lowered = name.lower()
    squashed = lowered.replace("-", "").replace("_", "").replace(" ", "")
    return lowered in _SENSITIVE_EXACT or any(
        fragment in squashed for fragment in _SENSITIVE_CONTAINS
    )


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """A copy safe to display or log: credential-bearing values are masked, order preserved."""
    return {
        name: MASK if is_sensitive_name(name) and value else value
        for name, value in headers.items()
    }


# 2026-08-05: params get the same treatment as headers. `to_curl` redacted headers only, so a key
# typed into a query parameter (`?api_key=sk-live-…`) rendered in clear in the very output the
# playground offers as "paste this to a colleague".
def redact_params(params: dict[str, str]) -> dict[str, str]:
    return {
        name: MASK if is_sensitive_name(name) and value else value for name, value in params.items()
    }


def resolve_placeholders(request: HttpRequest, resolver: Callable[[str], str]) -> HttpRequest:
    """A copy with every `{{secret:<ref>}}` in the URL, headers, params, and body replaced.

    `resolver` maps a ref to its secret (the UI passes a keychain lookup; tests pass a dict). The
    original request is untouched, so the resolved copy — which now holds real credentials — can
    be sent and dropped without the saved document ever containing a secret.
    """

    def _text(value: str) -> str:
        return _PLACEHOLDER.sub(lambda m: resolver(m.group(1)), value)

    return replace(
        request,
        url=_text(request.url),
        headers={k: _text(v) for k, v in request.headers.items()},
        params={k: _text(v) for k, v in request.params.items()},
        body=_text(request.body),
    )
