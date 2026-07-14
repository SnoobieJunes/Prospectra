# 2026-07-14 (P6): The saved mapping — how one REST endpoint becomes one table.
#
# This is the plan's "data-mapping tool": auth + pagination + JSONPath→columns, saved as a reusable
# mapping. It is a *document*, not code, so it round-trips into the project file, can be shared, and
# a SaaS plugin (see plugins/prospectra_jira) is little more than a factory for one of these.
#
# The secret NEVER lives here. `secret_ref` names a keychain entry (core/llm/secrets.py's rule,
# applied to connectors): the mapping in the project file says *which* credential to use, and the
# credential itself sits in the OS keychain. A mapping is therefore safe to commit or email.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAPPING_SCHEMA = 1

AUTH_KINDS = ("none", "bearer", "basic", "header", "query")
PAGINATION_KINDS = ("none", "page", "offset", "cursor", "link")

DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 20  # a runaway paginator is the classic way to hammer someone's API


@dataclass
class Column:
    name: str  # the column name in the resulting table
    path: str  # a path within one record, e.g. "fields.summary"

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Column:
        return cls(name=str(doc["name"]), path=str(doc["path"]))


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


@dataclass
class Pagination:
    kind: str = "none"
    # page:   ?page=1&per_page=100      -> page_param, size_param, start
    # offset: ?offset=0&limit=100       -> offset_param, size_param
    # cursor: ?cursor=<token>           -> cursor_param + next_path (where the token lives)
    # link:   RFC 5988 Link: rel="next" -> next_path may name a URL field in the body instead
    page_param: str = "page"
    size_param: str = "per_page"
    offset_param: str = "offset"
    cursor_param: str = "cursor"
    next_path: str = ""  # path to the next cursor/URL in the response body
    total_path: str = ""  # optional: path to a total count, used only for a progress message
    page_size: int = DEFAULT_PAGE_SIZE
    start: int = 1  # page numbering base (GitHub starts at 1, some APIs at 0)
    max_pages: int = DEFAULT_MAX_PAGES

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "page_param": self.page_param,
            "size_param": self.size_param,
            "offset_param": self.offset_param,
            "cursor_param": self.cursor_param,
            "next_path": self.next_path,
            "total_path": self.total_path,
            "page_size": self.page_size,
            "start": self.start,
            "max_pages": self.max_pages,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Pagination:
        return cls(
            kind=str(doc.get("kind", "none")),
            page_param=str(doc.get("page_param", "page")),
            size_param=str(doc.get("size_param", "per_page")),
            offset_param=str(doc.get("offset_param", "offset")),
            cursor_param=str(doc.get("cursor_param", "cursor")),
            next_path=str(doc.get("next_path", "")),
            total_path=str(doc.get("total_path", "")),
            page_size=int(doc.get("page_size", DEFAULT_PAGE_SIZE)),
            start=int(doc.get("start", 1)),
            max_pages=int(doc.get("max_pages", DEFAULT_MAX_PAGES)),
        )


@dataclass
class RestMapping:
    """One endpoint -> one table. Serializable, so it lives in the project file and is reusable."""

    name: str = "api_table"
    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    auth: Auth = field(default_factory=Auth)
    pagination: Pagination = field(default_factory=Pagination)
    records_path: str = ""  # where the rows live, e.g. "issues" or "data.items"
    columns: list[Column] = field(default_factory=list)  # empty = flatten every top-level key
    max_records: int = 10_000

    def validate(self) -> None:
        if not self.url.strip():
            raise ValueError("the mapping needs a URL")
        if not self.url.lower().startswith(("http://", "https://")):
            raise ValueError("the URL must be http(s)")
        if self.auth.kind not in AUTH_KINDS:
            raise ValueError(f"unknown auth kind {self.auth.kind!r}")
        if self.pagination.kind not in PAGINATION_KINDS:
            raise ValueError(f"unknown pagination kind {self.pagination.kind!r}")
        if self.auth.kind == "header" and not self.auth.header:
            raise ValueError("header auth needs the header's name")
        if self.auth.kind == "query" and not self.auth.param:
            raise ValueError("query auth needs the parameter's name")
        if self.pagination.kind == "cursor" and not self.pagination.next_path:
            raise ValueError("cursor pagination needs the path to the next cursor")
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("two columns share a name")

    # -- persistence ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_schema": MAPPING_SCHEMA,
            "name": self.name,
            "url": self.url,
            "method": self.method,
            "headers": dict(self.headers),
            "params": dict(self.params),
            "auth": self.auth.to_dict(),
            "pagination": self.pagination.to_dict(),
            "records_path": self.records_path,
            "columns": [c.to_dict() for c in self.columns],
            "max_records": self.max_records,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> RestMapping:
        version = int(doc.get("mapping_schema", MAPPING_SCHEMA))
        if version > MAPPING_SCHEMA:
            raise ValueError(
                f"Mapping schema v{version} is newer than this app supports (v{MAPPING_SCHEMA})"
            )
        return cls(
            name=str(doc.get("name", "api_table")),
            url=str(doc.get("url", "")),
            method=str(doc.get("method", "GET")),
            headers=dict(doc.get("headers", {})),
            params=dict(doc.get("params", {})),
            auth=Auth.from_dict(doc.get("auth", {})),
            pagination=Pagination.from_dict(doc.get("pagination", {})),
            records_path=str(doc.get("records_path", "")),
            columns=[Column.from_dict(c) for c in doc.get("columns", [])],
            max_records=int(doc.get("max_records", 10_000)),
        )
