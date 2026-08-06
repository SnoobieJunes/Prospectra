# P7 — API Playground + Field Mapper + Destinations

## Context

Prospectra can read APIs but only through a rigid "mapping" form, and it can only ever *read*.
There is no way to explore an unfamiliar endpoint, and no way to push anything back out.

The problem this solves is one the user has hit repeatedly in professional work: **everyone is
using the same data but calling it different things.** In the fashion world there are 50 ways to
say "product name" — and a matching 50 ways to say "navy". Today reconciling two systems means a
developer writing bespoke SQL. The goal is to let a **non-technical user** do it: pull data from an
API in a Postman-style playground, drag source columns onto destination fields, attach plain-English
transformations (truncate, join two fields, split on a character, translate values), see the result
before committing, and push it to a local dataset or back out over HTTP.

Three properties are non-negotiable, because they are what make this safe for that user:

1. **No raw SQL is ever typed.** Transformations are a closed, descriptor-driven vocabulary.
2. **Nothing is silent.** Truncated crosswalks, unreadable values, capped pages, failed rows — all
   stated, per the project's existing "confess when you hit a cap" rule.
3. **A live write cannot happen by accident.** See "The write-back hazard" below.

Delivered scope (confirmed with the user): full pipeline, with the REST write sequenced **last**;
value-level crosswalks in scope (inline + file-backed); the mapper is a **flow node with a dedicated
full-panel editor**; match suggestions score **both column names and sampled values**.

---

## What already exists (reuse, do not rebuild)

| Need | Existing thing | Path |
|---|---|---|
| HTTP with injectable transport | `httpx.Client(transport=…)`, `httpx.MockTransport` in tests | `core/connectors/rest/client.py:55` |
| Auth (5 kinds) | `Auth`, `_auth_headers()`, `_auth_params()` | `core/connectors/rest/{mapping,client}.py` |
| Pagination (5 kinds) with caps + confession | `RestClient._pages()`, `FetchReport` | `core/connectors/rest/client.py:150` |
| Response → columns inference | `infer_mapping_fields`, `records_to_frame` | `core/connectors/rest/flatten.py` |
| Tiny JSONPath | `parse`, `resolve`, `records_at` | `core/connectors/rest/paths.py` |
| Per-host rate limiting, Qt-free, injectable clock | `RateLimiter` | `core/scraper/rate_limit.py` |
| Descriptor→form pattern | `Field`/`Dialect` → `add_database.py` | `core/connectors/dialects.py` |
| Spec→validate→persist pattern | `ChartSpec` + `SPEC_SCHEMA` guard | `core/viz/spec.py` |
| **Generating a flow instead of hidden magic** | `flow_from_columns` | `core/flow/build.py:23` |
| Node escape hatch for external data | `Node.prepare(con)` | `core/flow/node.py:56` |
| SQL quoting (Windows-safe) | `ident`, `str_lit`, `path_lit` | `core/sqlutil.py` |
| Column list currency `(name, dtype)` | `Catalog.describe()` via `DESCRIBE … LIMIT 0` | `core/catalog/catalog.py:167` |
| DnD vocabulary | `MIME_COLUMN`, `ColumnPayload`, `column_mime`, `read_column` | `ui/dnd/mime.py` |
| Virtualized grid, injected fetcher | `DuckTableModel` | `ui/data/grid_model.py` |
| Off-GUI-thread work | `run_in_pool(fn, *a, on_result=, on_error=)` | `ui/workers.py` |
| Adding a workspace tab | `_PLACEHOLDERS` + overrides dict | `ui/tabs.py` |
| Upsert-by-id pattern to copy | `save_dashboard` `ON CONFLICT(id) DO UPDATE` | `core/project/store.py:236` |
| Real-drop test helper | `drop_on(widget, mime)` | `tests/test_ui_dnd.py:46` |

---

## Load-bearing design decisions

**Nested params are already supported.** `FlowGraph.to_doc()` emits `"params": inst.node.params`
verbatim (`graph.py:161`) and the store `json.dumps`es it. A `MappingDoc` goes into params **as a
dict, not as a JSON string** — a string would double-encode, be unreadable in a project diff, and
turn a malformed doc into a compile-time crash.

**`ParamField.default` is a shared reference.** `Node.__init__` does
`{f.name: f.default for f in self.params_schema}` (`node.py:40`). A mutable default would be shared
across every instance in the process — two mapping nodes on one canvas would edit each other.
Default must be `None`; the node normalizes to a fresh dict in `__init__`.

**Custom editors key on `ParamField.kind`, not node type.** That keeps the project's "a descriptor
drives the form" rule. And `ParamsEditor._make_widget` must **stop falling through to `QLineEdit`
for unknown kinds** — today it would `str(dict)` a mapping doc into a text box and write back
corrupted Python repr on focus-out. That is data loss, not cosmetics.

**No new SQLite tables.** `ProjectStore.open()` has **no migration path** (`store.py:137-161`) — it
only rejects *newer* versions. A new table forces `SCHEMA_VERSION = 2` and makes every touched
project unopenable by older builds. Requests, mappings and destinations all persist as rows in the
existing `connections` table, discriminated by `connector_type`
(`rest` / `rest_write` / `field_mapping`). Old builds open the file and ignore the rows.

**The write-back hazard.** `graph.output_nodes()` is `category == "output"` with no opt-in
(`graph.py:149`) and `FlowRunner.run()` executes every one of them (`runner.py:83`). The moment a
REST-PUT node carries that category, **pressing "Run flow" fires live PUTs at a production API.**
Four guards ship together, and none is sufficient alone:
- `Node.destructive: ClassVar[bool] = False`; `RestWriteNode.destructive = True`
- `FlowRunner.run(graph, *, only=None, allow_writes=False, dry_run=False)` raises unless opted in
- `run-flow --allow-writes` on the CLI; without it, a flow containing a write **exits 2 and names
  the node** (silently skipping is worse — the user believes it ran)
- dry-run default in the UI plus a typed confirmation before the first real request

**Split means `split_part`, never `unnest`.** A 1:1 "split on a character, keep piece N" is a
projection and belongs in the mapper. A row-multiplying split is not a projection at all and cannot
be a mapping step — it would break the one-row-in-one-row-out mental model the whole UI rests on.
Out of scope; note it for a future `explode` node.

**NULL semantics: `concat_ws`, which skips NULLs.** `"a" || ' - ' || NULL` is `NULL` — a product
with no colourway would vanish. `concat_ws(' - ', a, NULL)` yields `"a"`. Stated in field help.

**`cast` is choice-constrained.** `select.py:54` interpolates an unvalidated type string into
`CAST(… AS …)` — a pre-existing injection point. Do not copy it. Every numeric arg is `int()`-coerced
before it reaches an f-string; every type is a closed `choice`.

**Do not add a second plugin entry point yet.** `load_external_nodes()` (`node.py:74`) has zero call
sites — the documented `prospectra.flow_nodes` extension point does not function. Wire that one up
first (Slice 4, one line + a test). A `prospectra.mapping_transforms` group can follow later.

---

## Data model

### Transform — a descriptor, not a class (mirrors `dialects.py`)

```python
# core/mapping/transforms.py
@dataclass(frozen=True)
class ArgSpec:
    name: str; label: str
    kind: str                      # string | int | choice | pairs | path
    default: Any = ""
    choices: tuple[str, ...] = ()
    help: str = ""

@dataclass(frozen=True)
class Transform:
    key: str
    label: str                     # "Split and keep part"
    summary: str                   # user-facing: "Split on a character, keep the Nth piece"
    args: tuple[ArgSpec, ...]
    build: Callable[[str, dict[str, Any]], str]   # (sql_expr, coerced_args) -> sql_expr
    result_type: str = "VARCHAR"
    status: str = "verified"       # verified | advanced

TRANSFORMS: tuple[Transform, ...]
TRANSFORMS_BY_KEY: dict[str, Transform]
def coerce_args(t: Transform, raw: dict[str, Any]) -> dict[str, Any]
```

`build` is never serialized (same as `Dialect`); the doc stores `key` + `args`. **`coerce_args` runs
before `build` and is the injection boundary** — `build` can never see a string where an int is
declared. The UI renders each transform's arg form generically from `args`, exactly as
`add_database.py` renders a `Dialect`.

Vocabulary: `trim` · `upper` · `lower` · `title` · `truncate(length)` · `prepend(text)` ·
`append(text)` · `replace(find, with)` · `split_part(sep, index)` · `regex_extract(pattern, group)` ·
`regex_replace(pattern, with)` · `pad(length, char, side)` · `default(value)` · `round(places)` ·
`lookup(pairs | file)` · `cast(type∈CAST_TYPES)` · `parse_date(format)` · `date_format(format)` ·
`expression(sql)` marked `status="advanced"`, hidden behind a disclosure and **never suggested**.

### Mapping document (spec→validate→persist, like `ChartSpec`)

```python
# core/mapping/doc.py
MAPPING_DOC_SCHEMA = 1
UNMAPPED_POLICIES = ("drop", "passthrough", "null")

@dataclass
class Step:      key: str; args: dict[str, Any]
@dataclass
class FieldMap:
    target: str
    sources: list[str] = []        # 0 = constant or NULL; >1 = concat_ws
    join_with: str = " "
    steps: list[Step] = []
    constant: str = ""
    note: str = ""                 # why this mapping exists — the audit trail for "50 names"
@dataclass
class TargetColumn:  name: str; type: str = "VARCHAR"; required: bool = False
@dataclass
class MappingDoc:
    name: str; source: str; target: str
    target_columns: list[TargetColumn]
    fields: list[FieldMap]
    unmapped_policy: str = "drop"
    def validate(self) -> None
    def to_dict(self) / from_dict(cls, doc)     # schema guard, refuses newer
```

`target_columns` is what lets `validate()` say **"styleCode is required and nothing is mapped to
it."** That sentence is the entire non-technical-safety value. It is populated from
`Catalog.describe()` for a local target, `FlowRunner.columns()` for a flow node, or
`infer_mapping_fields()` over a sample response / pasted JSON for an API target.

### Worked example — a vendor feed into a PIM

`prod_nm` + `colorway` → `styleDescription` (join with " - ", truncate 40);
`sku_raw` → `styleCode` (split on "-" keep piece 1, uppercase); `retailPrice` unmapped.

```python
MappingDoc(
  name="vendor_feed_to_pim", source="vendor_csv", target="pim_products",
  target_columns=[TargetColumn("styleCode","VARCHAR",required=True),
                  TargetColumn("styleDescription","VARCHAR",required=True),
                  TargetColumn("retailPrice","DECIMAL(18,4)")],
  fields=[FieldMap(target="styleDescription", sources=["prod_nm","colorway"], join_with=" - ",
                   steps=[Step("truncate", {"length": 40})],
                   note="vendor splits name and colourway; PIM wants one 40-char line"),
          FieldMap(target="styleCode", sources=["sku_raw"],
                   steps=[Step("split_part", {"sep":"-","index":1}), Step("upper", {})],
                   note="vendor SKU is STYLE-COLOR-SIZE; PIM wants the style segment")],
  unmapped_policy="null")
```

### Compile algorithm

```
compile_select(doc, source_rel, available=None):
  1. doc.validate()
  2. if available: reject any FieldMap.sources not present, naming them
  3. per FieldMap:
       base = str_lit(constant)                     if no sources and constant
              "CAST(NULL AS VARCHAR)"               if no sources
              ident(sources[0])                     if one source  (type preserved)
              concat_ws(str_lit(join_with), *idents) if many       (NULL-skipping)
       expr = fold steps left-to-right through TRANSFORMS_BY_KEY[key].build
       if declared target type and (steps or len(sources) != 1):
           expr = TRY_CAST(expr AS <declared>)      # TRY_, never CAST
       emit f"{expr} AS {ident(target)}"
  4. unmapped_policy:
       "null"        -> CAST(NULL AS <type>) AS <name> for each unmapped TargetColumn
       "passthrough" -> prepend "* EXCLUDE (<consumed ∩ available>)"; requires `available`
       "drop"        -> nothing
  5. "SELECT " + ", ".join(projections) + " FROM " + source_rel
```

Emitted SQL for the example (`source_rel = "n0"`, one CTE — the `count("WITH") == 1` test is
untouched):

```sql
SELECT
  TRY_CAST(substr(concat_ws(' - ', "prod_nm", "colorway"), 1, 40) AS VARCHAR) AS "styleDescription",
  TRY_CAST(upper(split_part("sku_raw", '-', 1)) AS VARCHAR) AS "styleCode",
  CAST(NULL AS DECIMAL(18,4)) AS "retailPrice"
FROM n0
```

`coercion_check_sql(doc, rel)` emits, per TRY_CAST'd field,
`count(*) FILTER (WHERE <expr> IS NOT NULL AND TRY_CAST(<expr> AS T) IS NULL) AS "<target>__lost"` —
that is how *"37 rows could not be read as a price"* gets stated instead of silently NULLed. The same
technique counts crosswalk misses.

### Crosswalks

Inline (≤ 50 pairs, edited as a 2-column grid) compiles to
`COALESCE(map_extract(MAP {…}, expr)[1], expr)` and stays inside the single CTE. File-backed
crosswalks are materialized by `MapFieldsNode.prepare(con)` into `xwalk_<sha1>` and referenced by an
**uncorrelated** MAP subquery. A crosswalk over the size cap truncates and says so.

---

## Slices

Each ends in something runnable and testable.

### 1 — `core/http/` (Qt-free), and two real bugs die
New `core/http/{__init__,request,send,curl}.py`:
`HttpRequest(method, url, headers, params, body_kind∈("none","json","text","form"), body, auth,
timeout, follow_redirects)` with `validate/to_dict/from_dict`;
`HttpResponse(status, reason, headers, text, json, elapsed_ms, size_bytes, error)` + `.ok`;
`send(request, secret=None, *, transport=None, limiter=None) -> HttpResponse` — **non-raising**, so a
404 with a helpful JSON error body is a result to display, not an exception;
`to_curl(request, redact=True)`; `redact_headers()`; `resolve_placeholders()` for `{{secret:<ref>}}`.

- **`RestMapping.headers` is currently dead** — declared, serialized, deserialized, never sent
  (`client.py:102` passes only `_auth_headers()`). Refactoring `_get` through `send()` fixes it.
- Preserve the `params=params or None` semantic verbatim (`client.py:97-102`); dropping it makes the
  Link paginator re-fetch page 1 forever.
- `RestMapping` gains `body_kind`, `body`, `rate_limit_per_sec`; **`MAPPING_SCHEMA = 2`** (v1 docs
  load unchanged; the existing guard correctly refuses v2 in older builds).
- `RestClient` accepts a `RateLimiter`; `RestConnector.sample()` stops reaching into `client._get`.
- CLI `prospectra api-send <request.json> [--secret-ref REF]`.

### 2 — Playground UI + persistence that comes back
`ui/api/{request_editor,response_view,playground}.py`. Method combo, URL, tabbed
Params / Headers (key-value grids — **neither has any UI today**) / Auth / Body. Response pane:
status pill, elapsed, size, Pretty / Raw / Headers, plus a tabular view via `DuckTableModel` when the
body is an array of flat objects. Send through `run_in_pool(send, …)`. "Save as data source" hands a
`RestMapping` to the existing catalog path.

`store.py`: `save_connection(..., connection_id=None)` upsert copying `save_dashboard`'s
`ON CONFLICT(id) DO UPDATE` (`store.py:236-253`), plus `get_connection`/`delete_connection`, and
**call `list_connections()` on project open** — today it has exactly one caller (a test), which is
why saved API sources never come back.

`ui/tabs.py` gains the tab; **`tests/test_ui_smoke.py:16` hard-asserts the four current tab names**
and must be updated.

### 3 — `core/mapping/` (Qt-free, headless)
`transforms.py`, `doc.py`, `compile.py`, `abbrev.py`, `suggest.py`.
`suggest_matches(source_cols, target_cols, min_confidence=0.45) -> list[Suggestion]` blends
token-Jaccard (0.5, after camel/snake splitting and abbreviation expansion — `nm→name`, `clr→color`,
`qty→quantity`, `desc→description`), `difflib.SequenceMatcher` (0.3), and dtype compatibility (0.2).
`suggest_from_values(con, source_rel, target_rel, pairs, sample=200)` scores overlap of sampled
distinct values — **this is the one that matches `c1` to `colour_code`; names lie, values don't.**
Suggestions are always proposals the user accepts, never applied silently.
CLI: `prospectra map --source … --doc … --out …` and `prospectra suggest-map --source … --target …`.

### 4 — The node, the cheap schema call, the editor hatch
`core/flow/nodes/map_fields.py` — `MapFieldsNode`, `category="transform"`, one
`ParamField("doc", "Field mapping", "mapping_doc", default=None)`, `__init__` copying to a fresh
dict, `validate()` delegating to `MappingDoc.validate()`, `compile()` to `compile_select`,
`prepare()` materializing file-backed crosswalks.

`runner.py`: `columns(graph, node_id)` via the cheap `DESCRIBE … LIMIT 0` idiom already used at
`catalog.py:169`, **cached on the compiled SQL string** (keying on `node_id` goes stale on any
upstream edit); `preview_select(graph, upstream_id, select_sql, limit=20)` powering live
before/after per field — without it the mapper is guesswork; `_prepare` gains a `prepared: set[str]`
guard, because it currently runs **per output node** (`runner.py:84`) and would duplicate a live API
fetch across two outputs.

`ui/flow/params_editor.py`: module-level `CUSTOM_EDITORS: dict[str, Callable[…, QWidget]]` keyed on
`kind`, consulted first, **and no `QLineEdit` fallthrough for unknown kinds**.
Wire `load_external_nodes()` into `core/flow/__init__.py` + a test — fixing an extension point that
is documented in `CONTRIBUTING.md` and does not currently work.

### 5 — The drag-and-drop mapper
`ui/dnd/drop_target.py` — `DropTargetMixin` factoring out the `dragEnter/dragLeave/drop` +
`_style(active)` `#2a78d6` treatment currently duplicated across four widgets; retrofit all four in
this slice or there will be five copies.
`ui/mapping/{mapper_panel,field_row,transform_chip}.py` — source columns (drag source) | field rows
(drop targets, one per target column, showing chips + live before/after) | target columns. Unmapped
required targets are visibly flagged. Test seam `MapperPanel.drop_columns(target, payload)`
mirroring `SourcesDock.drop_columns()`. A guided "Map to…" action generates the flow, following
`build.py:flow_from_columns` — the drop **writes a flow** rather than doing hidden magic.
Re-validate against `FlowRunner.columns()` on open and paint broken fields red: an upstream rename
silently kills a saved mapping and `validate()` cannot see it.

### 6 — Generalize the write path, local destinations
`core/flow/write.py`: `RowFailure`, `WriteReport(attempted, written, failed, skipped, dry_run,
stopped_early, failures, notes)`.
`Node.write(con, sql, *, dry_run=True) -> WriteReport` defaulting to
`raise NotImplementedError(f"{type(self).type_name} cannot write")` — a silent no-op would report
success having done nothing. `Node.destructive: ClassVar[bool] = False`.
`runner.py:86-102`: delete the hard-coded `params["path"]` / `COPY` block, call `node.write(...)`.
`OutputNode.write()` holds today's exact COPY behaviour **including the DuckDB-1.5 PIVOT quirk
comment at `runner.py:95-98`**. `OutputResult = WriteReport` alias with `.path`/`.rows` properties so
`cli.py:280`'s `f"wrote {result.path} ({result.rows} rows)"` and its tests are unaffected.
New `core/flow/nodes/output_dataset.py` — `CREATE OR REPLACE TABLE … AS <sql>` into the catalog.

### 7 — The REST write
`core/http/write.py`: `WriteSpec(url_template, method, key_column, body_kind, mode∈("per_row",
"batch"), chunk, max_rows=1000, max_consecutive_failures=5, rate_per_sec, idempotency, auth,
headers)` and `push_rows(spec, rows, secret=None, *, dry_run=True, transport=None, limiter=None,
on_progress=None) -> WriteReport`.
`core/flow/nodes/output_rest.py` — `RestWriteNode`, `destructive=True`, `validate()` rejecting a
missing URL template or key column **before any request goes out** (`validate_ready` is the
pre-flight seam, `graph.py:104`).

Rails: `per_row` default so a 400 is attributable to a specific row — that attribution *is* the
product for a non-technical user; PUT/PATCH require a key column and a URL template
(`…/products/{styleCode}`); POST requires explicit acknowledgement and sends a content-hash
`Idempotency-Key`; a **consecutive-failure circuit breaker (5)** so one bad mapping cannot fire
10,000 failing PUTs; a 1,000-row cap that confesses; retry only on 429/5xx honouring `Retry-After`,
**never on 4xx**; `RateLimiter` per host. **`WriteReport.notes` must reach the UI** — `FetchReport.notes`
currently dies in a `logger.info` and already violates the project's own rule.
Recovery: export `failures` to CSV and accept `only_keys` for a targeted re-run. Say plainly that
resume is manual.
CLI: `run-flow --allow-writes` / `--dry-run`, printing notes and failures.

---

## Verification

**Headless core** — `test_http_send.py` (200/404/500 never raise; `.error` on network failure;
`redact_headers` masks `Authorization`; `{{secret:}}` substitution; **`params=None` when empty**,
regression-locking the Link-paginator bug); `test_rest_client_headers.py` (a mapping with
`headers={"X-Tenant":"acme"}` transmits it — **this test fails today** and is the proof the bug is
dead); `test_mapping_transforms.py` (parametrized over `TRANSFORMS`, every `build` executes in
DuckDB; `truncate` with `length="40; DROP"` raises at coercion; `cast` rejects a type outside
`CAST_TYPES`); `test_mapping_compile.py` (the worked example asserts the **exact SQL above**, then
executes it and asserts `("Oxford Shirt - Navy", "AB1234")`; NULL colourway yields `"Oxford Shirt"`;
all three unmapped policies); `test_mapping_suggest.py` (`prod_nm`→`productName` clears threshold —
the case difflib alone fails; `suggest_from_values` matches on values when names share nothing);
`test_http_write.py` (`dry_run` issues **zero** requests; 5 consecutive failures trips the breaker;
row cap sets a note; 429 retries and 400 does not; stable `Idempotency-Key`);
`test_flow_runner_write.py` (a `destructive` node raises without `allow_writes`; `_prepare` runs each
ancestor **once** across two outputs; `columns()` cache invalidates on an upstream param edit);
`test_project_store.py` (same-id `save_connection` updates rather than duplicating; a `RestMapping`
round-trips back out).

**CLI** — `api-send` against a `file://` fixture; `map` produces the expected CSV; `suggest-map`
prints the expected pair; `run-flow` on a flow containing a REST write **exits 2 and names the node**
without `--allow-writes`.

**pytest-qt** (house style: private attrs, explicit seams) — `RequestEditor.request()` reflects typed
values and the displayed request masks `Authorization`; the mapper drop path driven through
`drop_on(widget, mime)` from `tests/test_ui_dnd.py:46` with a real `ColumnPayload`, asserting
`panel.doc().fields[0].sources == ["prod_nm"]`; a `ParamField` of unknown kind renders **no**
`QLineEdit` (locks the corruption bug); two `MapFieldsNode` instances do not share a params dict;
`test_ui_smoke.py` tab list updated.

**End to end, by hand** — `uv run prospectra`: playground → GET a live public JSON API → save as a
data source → open a local CSV → drag columns onto its fields with a lookup crosswalk → preview →
write to a local dataset. Then a dry-run REST write against a scripted local endpoint. Per the
project's rule, **nothing is claimed working until it has been run and observed**, and Windows is
claimed only from CI (`.github/workflows/ci.yml` runs the suite plus a real GUI launch on all three).

Gates: `uv run pytest` · `uv run ruff check .` · `uv run mypy prospectra` · `uv run lint-imports`
(the last enforces `core` ↛ Qt — all of `core/http/` and `core/mapping/` must stay Qt-free).

---

## Honest risks

- **The REST write is the most dangerous thing in this app.** A non-technical user, a wrong mapping
  and a live endpoint is an unrecoverable event on someone else's system. The four guards ship
  together or the write does not ship.
- **`Idempotency-Key` is only as good as the target API** — honoured by Stripe-class APIs, ignored by
  most. For POST this is a visible "may duplicate on retry" caveat in the UI, not a docstring.
- **`WriteReport.failures` is not a resume log.** Real resumability needs durable per-row outcomes.
- **Playground bodies are a secrets-leak vector** into a file the codebase documents as safe to
  email. `{{secret:}}` templating plus a save-time entropy warning is mitigation, not a guarantee.
- **`parse_date` is the highest-risk correctness area** — a wrong layout string makes `try_strptime`
  silently NULL an entire column. `coercion_check_sql` reporting the count is what keeps it honest.
- **DuckDB edge semantics will surprise the tests:** `concat_ws` over all-NULL returns `''` not NULL;
  `regexp_extract` returns `''` on no match; `split_part` past the last piece returns `''`. Assert
  these explicitly. The `title` transform's `\U` backreference is RE2-dependent — verify before
  labelling it `verified`, else ship a `CASE` fallback.
- **A saved mapping breaks silently on an upstream rename.** UI re-validation is the only defence and
  it does not protect headless `run-flow`, where the failure is a raw DuckDB message in a
  `FlowRunError`.
- **The transform vocabulary is VARCHAR-centric**; numeric and date work will feel second-class and
  will need a follow-up pass.
- Deviations from this plan go in `Deviations.md` tagged to the commit, per CLAUDE.md.
