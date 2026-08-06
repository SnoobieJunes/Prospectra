# 2026-07-31 (P7): Output: REST Write — the node that makes a flow push rows OUT over HTTP.
#
# `destructive = True` is the load-bearing line: it is what makes FlowRunner.run() and the CLI
# refuse this node without explicit consent (see runner.py / cli.py). The node itself validates
# its spec BEFORE any request goes out — `validate_ready` calls validate() on the whole ancestry,
# so a missing URL template or key column stops the run at the pre-flight, not mid-write.

from __future__ import annotations

from typing import Any, ClassVar

import duckdb

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.flow.write import WriteReport
from prospectra.core.http.write import WriteSpec, push_rows
from prospectra.core.llm import secrets as secret_store


@register
class RestWriteNode(Node):
    type_name = "output_rest"
    display_name = "Output: REST Write"
    category = "output"
    destructive: ClassVar[bool] = True  # live PUTs at someone else's system — never by accident
    params_schema: ClassVar = (
        ParamField(
            "spec",
            "REST destination",
            "write_spec",
            default=None,  # None, never a dict — ParamField defaults are shared by reference
            help="URL template, method, key column, and the rails (caps, retries, rate).",
        ),
        ParamField(
            "only_keys",
            "Only these keys (comma list)",
            "string",
            "",
            help="Targeted re-run: push only rows whose key column matches. Recovery is "
            "manual — export a failed run's rows, fix, re-run with their keys here.",
        ),
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        if not isinstance(self.params.get("spec"), dict):
            self.params["spec"] = WriteSpec().to_dict()
        self.transport: Any = None  # tests inject httpx.MockTransport here

    def spec(self) -> WriteSpec:
        return WriteSpec.from_dict(self.params["spec"])

    def validate(self) -> None:
        # The whole point: a broken destination dies HERE (validate_ready's pre-flight), before
        # a single request exists.
        self.spec().validate()

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {inputs[0]}"

    def write(
        self, con: duckdb.DuckDBPyConnection, sql: str, *, dry_run: bool = True
    ) -> WriteReport:
        spec = self.spec()
        cursor = con.execute(sql)
        columns = [str(d[0]) for d in cursor.description or []]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

        secret = None
        if spec.auth.kind != "none" and spec.auth.secret_ref:
            secret = secret_store.get_api_key(spec.auth.secret_ref)
        if spec.auth.kind != "none" and not secret and not dry_run:
            raise ValueError(
                f"this write uses {spec.auth.kind} auth but {spec.auth.secret_ref!r} is not in "
                "the OS keychain — nothing was sent"
            )

        only_keys_raw = str(self.params.get("only_keys", "")).strip()
        only_keys = (
            [part.strip() for part in only_keys_raw.split(",") if part.strip()]
            if only_keys_raw
            else None
        )
        return push_rows(
            spec,
            rows,
            secret,
            dry_run=dry_run,
            transport=self.transport,
            only_keys=only_keys,
        )
