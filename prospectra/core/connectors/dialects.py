# 2026-07-14 (P6): Dialect descriptors — the mechanism that turns "support 15 warehouses" into a
# data table instead of 15 connector classes.
#
# One generic SQLAlchemy connector already talks to every dialect (P1). What was missing was the
# *form*: a user should not have to know that Snowflake's URL wants an `account` in the host slot
# and BigQuery's wants the project id and no credentials at all. A descriptor declares the fields,
# the URL template, and the driver package — and the UI renders a form from it. Adding a dialect is
# one entry in this file; no new class, no new dialog.
#
# Two honesty rules are enforced here, not decorated on afterwards:
#   * `status` is "experimental" for every dialect this repo has not run against a real server.
#     Only SQLite is "verified", because only SQLite is in the test suite. Flipping one requires a
#     real connection observed by a human — nothing else counts (CLAUDE.md).
#   * Credentials are URL-quoted. A password containing "@" or "/" (common, and exactly the kind of
#     thing a strong generator produces) silently corrupts a hand-built URL; `quote_plus` is the
#     difference between "wrong password" and "connects".

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
from urllib.parse import quote, quote_plus

from prospectra.core.connectors.base import ConnectorStatus


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    required: bool = True
    secret: bool = False  # -> masked in the UI, and stored in the OS keychain, never the project
    default: str = ""
    help: str = ""
    # 2026-07-14 (P6): a path is not a credential, and quoting it like one breaks it. Escaping the
    # slashes of "sqlite:///C:/data/sales.db" produced "sqlite:///C%3A%2Fdata%2Fsales.db" — and
    # SQLAlchemy did NOT fail on that. It quietly created a new empty database at that literal
    # name and reported a successful connection with zero tables. Found by running the acceptance
    # path, not by any unit test. Path-like fields keep their separators; everything else is fully
    # escaped, because a password containing "@" or "/" must not be able to restructure the URL.
    path_like: bool = False

    # 2026-08-05: the P6 fix below was only half a fix — it kept `/` and `:` safe but not `\`, so
    # on WINDOWS every separator in "C:\Users\me\sales.db" still became %5C and the exact failure
    # described above happened anyway: SQLAlchemy created an empty database at that literal name,
    # reported a healthy connection, and every query then said "Table orders not found". Windows
    # CI had been red on this since P6.
    # Path-like values are normalized to POSIX separators first — the same rule
    # `prospectra.core.sqlutil.path_lit` already applies for SQL, and SQLite/SQLAlchemy accept
    # forward slashes on Windows. Only path-like fields are touched: a password containing a
    # backslash keeps it, and is still fully escaped.
    def quote_value(self, value: str) -> str:
        if not self.path_like:
            return quote_plus(value, safe="")
        return quote(value.replace("\\", "/"), safe="/:")


@dataclass(frozen=True)
class Dialect:
    key: str  # e.g. "snowflake"
    display_name: str
    template: str  # URL template, formatted with the (already quoted) field values
    fields: tuple[Field, ...]
    driver_package: str = ""  # pip/uv package that provides the SQLAlchemy dialect
    driver_module: str = ""  # importable module used to detect whether it is installed
    status: ConnectorStatus = "experimental"
    notes: str = ""

    @property
    def driver_installed(self) -> bool:
        """Is the dialect's driver importable right now?"""
        if not self.driver_module:
            return True  # built into SQLAlchemy (sqlite)
        try:
            return find_spec(self.driver_module) is not None
        except (ImportError, ValueError):
            return False

    def install_hint(self) -> str:
        return f"uv add {self.driver_package}" if self.driver_package else ""

    def build_url(self, values: dict[str, str]) -> str:
        """Render the SQLAlchemy URL. Every value is URL-quoted — see the module note."""
        missing = [
            f.label for f in self.fields if f.required and not values.get(f.name, "").strip()
        ]
        if missing:
            raise ValueError(f"{self.display_name} needs: {', '.join(missing)}")
        quoted = {f.name: f.quote_value(values.get(f.name, f.default).strip()) for f in self.fields}
        url = self.template.format(**quoted)
        # An optional field left blank leaves an empty segment behind ("host:/db" or a dangling
        # "?warehouse="); tidy the two shapes that actually occur rather than pretending they don't.
        return url.replace(":@", "@").rstrip("?&").replace("?&", "?")


_TEXT = Field


def _SECRET(name: str, label: str, *, required: bool = True, help: str = "") -> Field:
    return Field(name, label, required=required, secret=True, help=help)


DIALECTS: tuple[Dialect, ...] = (
    Dialect(
        key="sqlite",
        display_name="SQLite",
        template="sqlite:///{path}",
        fields=(_TEXT("path", "Database file", help="e.g. C:/data/sales.db", path_like=True),),
        status="verified",  # the only dialect this repo's tests actually run
        notes="Local file database. Verified by the test suite.",
    ),
    Dialect(
        key="postgresql",
        display_name="PostgreSQL",
        template="postgresql+psycopg://{user}:{password}@{host}:{port}/{database}",
        fields=(
            _TEXT("host", "Host"),
            _TEXT("port", "Port", default="5432"),
            _TEXT("database", "Database"),
            _TEXT("user", "User"),
            _SECRET("password", "Password", required=False),
        ),
        driver_package="psycopg[binary]",
        driver_module="psycopg",
    ),
    Dialect(
        key="mysql",
        display_name="MySQL / MariaDB",
        template="mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
        fields=(
            _TEXT("host", "Host"),
            _TEXT("port", "Port", default="3306"),
            _TEXT("database", "Database"),
            _TEXT("user", "User"),
            _SECRET("password", "Password", required=False),
        ),
        driver_package="pymysql",
        driver_module="pymysql",
    ),
    Dialect(
        key="mssql",
        display_name="Microsoft SQL Server",
        template="mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver={driver}",
        fields=(
            _TEXT("host", "Host"),
            _TEXT("port", "Port", default="1433"),
            _TEXT("database", "Database"),
            _TEXT("user", "User"),
            _SECRET("password", "Password", required=False),
            _TEXT("driver", "ODBC driver", default="ODBC Driver 18 for SQL Server"),
        ),
        driver_package="pyodbc",
        driver_module="pyodbc",
        notes=(
            "Needs the Microsoft ODBC driver installed on the machine, not just the Python package."
        ),
    ),
    Dialect(
        key="snowflake",
        display_name="Snowflake",
        template=(
            "snowflake://{user}:{password}@{account}/{database}/{schema}?warehouse={warehouse}"
            "&role={role}"
        ),
        fields=(
            _TEXT("account", "Account", help="e.g. xy12345.eu-central-1"),
            _TEXT("user", "User"),
            _SECRET("password", "Password"),
            _TEXT("database", "Database"),
            _TEXT("schema", "Schema", default="PUBLIC"),
            _TEXT("warehouse", "Warehouse", required=False),
            _TEXT("role", "Role", required=False),
        ),
        driver_package="snowflake-sqlalchemy",
        driver_module="snowflake.sqlalchemy",
    ),
    Dialect(
        key="bigquery",
        display_name="Google BigQuery",
        template="bigquery://{project}/{dataset}",
        fields=(
            _TEXT("project", "GCP project"),
            _TEXT("dataset", "Dataset", required=False),
        ),
        driver_package="sqlalchemy-bigquery",
        driver_module="sqlalchemy_bigquery",
        notes=(
            "Authenticates with Application Default Credentials — run `gcloud auth "
            "application-default login` first. No password is stored by Prospectra."
        ),
    ),
    Dialect(
        key="redshift",
        display_name="Amazon Redshift",
        template="redshift+redshift_connector://{user}:{password}@{host}:{port}/{database}",
        fields=(
            _TEXT("host", "Cluster endpoint"),
            _TEXT("port", "Port", default="5439"),
            _TEXT("database", "Database"),
            _TEXT("user", "User"),
            _SECRET("password", "Password"),
        ),
        driver_package="sqlalchemy-redshift redshift-connector",
        driver_module="redshift_connector",
    ),
    Dialect(
        key="databricks",
        display_name="Databricks SQL",
        template=(
            "databricks://token:{token}@{host}?http_path={http_path}&catalog={catalog}"
            "&schema={schema}"
        ),
        fields=(
            _TEXT("host", "Workspace host", help="e.g. dbc-1234.cloud.databricks.com"),
            _TEXT("http_path", "HTTP path", help="e.g. /sql/1.0/warehouses/abc123", path_like=True),
            _SECRET("token", "Access token"),
            _TEXT("catalog", "Catalog", required=False, default="hive_metastore"),
            _TEXT("schema", "Schema", required=False, default="default"),
        ),
        driver_package="databricks-sqlalchemy",
        driver_module="databricks",
    ),
    Dialect(
        key="athena",
        display_name="Amazon Athena",
        template=(
            "awsathena+rest://@athena.{region}.amazonaws.com:443/{database}"
            "?s3_staging_dir={s3_staging_dir}"
        ),
        fields=(
            _TEXT("region", "AWS region", default="us-east-1"),
            _TEXT("database", "Database", default="default"),
            _TEXT("s3_staging_dir", "S3 staging dir", help="s3://bucket/path/", path_like=True),
        ),
        driver_package="PyAthena[SQLAlchemy]",
        driver_module="pyathena",
        notes="Uses your ambient AWS credentials (env vars, ~/.aws/credentials, or an IAM role).",
    ),
    Dialect(
        key="trino",
        display_name="Trino / Presto",
        template="trino://{user}@{host}:{port}/{catalog}/{schema}",
        fields=(
            _TEXT("host", "Host"),
            _TEXT("port", "Port", default="8080"),
            _TEXT("user", "User"),
            _TEXT("catalog", "Catalog"),
            _TEXT("schema", "Schema", required=False, default="default"),
        ),
        driver_package="trino[sqlalchemy]",
        driver_module="trino",
    ),
    Dialect(
        key="oracle",
        display_name="Oracle",
        template="oracle+oracledb://{user}:{password}@{host}:{port}/?service_name={service_name}",
        fields=(
            _TEXT("host", "Host"),
            _TEXT("port", "Port", default="1521"),
            _TEXT("service_name", "Service name"),
            _TEXT("user", "User"),
            _SECRET("password", "Password"),
        ),
        driver_package="oracledb",
        driver_module="oracledb",
    ),
    Dialect(
        key="odbc",
        display_name="Any ODBC source (generic)",
        template="mssql+pyodbc://{user}:{password}@{dsn}",
        fields=(
            _TEXT("dsn", "DSN name", help="A DSN configured in your ODBC driver manager"),
            _TEXT("user", "User", required=False),
            _SECRET("password", "Password", required=False),
        ),
        driver_package="pyodbc",
        driver_module="pyodbc",
        notes=(
            "The escape hatch for sources with no SQLAlchemy dialect. Prospectra speaks to them "
            "through pyodbc's SQL Server dialect, which works for ODBC sources that accept "
            "T-SQL-ish queries; others may reject some SQL."
        ),
    ),
)

DIALECTS_BY_KEY: dict[str, Dialect] = {d.key: d for d in DIALECTS}


@dataclass(frozen=True)
class DialectForm:
    """A filled-in dialect form: the values, and the URL they produce."""

    dialect: Dialect
    values: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.dialect.build_url(self.values)


def redact_url(url: str) -> str:
    """Strip the password out of a SQLAlchemy URL.

    This is what goes into the project file. A .prospectra file gets emailed, committed, and
    attached to tickets; a password inside one is a leak with a long tail. The real credential
    lives in the OS keychain, and the connection record points at it by reference.
    """
    scheme, separator, rest = url.partition("://")
    if not separator or "@" not in rest:
        return url
    credentials, _at, host = rest.rpartition("@")
    user, colon, _password = credentials.partition(":")
    if not colon:
        return url
    return f"{scheme}://{user}:***@{host}"


def dialect_for_url(url: str) -> Dialect | None:
    """Best-effort reverse lookup — which descriptor produced (or matches) this URL?"""
    scheme = url.split("://", 1)[0].split("+", 1)[0].lower()
    aliases = {"postgresql": "postgresql", "postgres": "postgresql", "awsathena": "athena"}
    key = aliases.get(scheme, scheme)
    return DIALECTS_BY_KEY.get(key)
