# 2026-07-14 (P6): Generic JDBC — the last escape hatch, for databases with a JDBC driver and no
# SQLAlchemy dialect (Teradata, Vertica, DB2, SAP HANA, Exasol, and every in-house thing).
#
# It needs a JVM and a driver .jar, so `jaydebeapi` is an optional extra (`uv sync --extra jdbc`)
# and the JVM requirement is stated up front rather than discovered as a stack trace. Everything
# here is "experimental": no JDBC driver has been run from this build.

from __future__ import annotations

import logging
from typing import Any, ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef

logger = logging.getLogger(__name__)

_MISSING = (
    "JDBC support needs the optional extra and a Java runtime:\n"
    "  uv sync --extra jdbc      (installs jaydebeapi + JPype)\n"
    "and a JVM on this machine (java -version must work), plus the vendor's driver .jar."
)


class JDBCConnector(Connector):
    type_name = "jdbc"
    display_name = "Database (generic JDBC)"
    status: ClassVar = "experimental"  # no JDBC driver has been exercised from this build

    def __init__(
        self,
        jdbc_url: str,
        driver_class: str,
        jars: list[str] | None = None,
        user: str = "",
        password: str = "",
    ) -> None:
        self.jdbc_url = jdbc_url
        self.driver_class = driver_class
        self.jars = jars or []
        self._user = user
        self._password = password
        self._connection: Any = None

    # -- lifecycle ---------------------------------------------------------------------------

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            import jaydebeapi
        except ImportError as exc:  # the extra is not installed
            raise ConnectorError(_MISSING) from exc
        try:
            self._connection = jaydebeapi.connect(
                self.driver_class,
                self.jdbc_url,
                [self._user, self._password] if self._user else None,
                self.jars or None,
            )
        except Exception as exc:  # JPype raises JVM-specific errors; surface them plainly
            raise ConnectorError(
                f"JDBC connection failed: {exc}\n\n"
                "Check the driver class name, the .jar path, and that a JVM is installed."
            ) from exc
        return self._connection

    def test_connection(self) -> None:
        cursor = self.connect().cursor()
        try:
            cursor.execute("SELECT 1")
            cursor.fetchall()
        except Exception as exc:
            raise ConnectorError(f"JDBC connection test failed: {exc}") from exc
        finally:
            cursor.close()

    # -- Connector contract ---------------------------------------------------------------------

    def list_datasets(self) -> list[DatasetRef]:
        connection = self.connect()
        try:
            meta = connection.jconn.getMetaData()
            result = meta.getTables(None, None, "%", ["TABLE", "VIEW"])
            names: list[str] = []
            while result.next():
                names.append(str(result.getString("TABLE_NAME")))
        except Exception as exc:
            raise ConnectorError(f"Could not list JDBC tables: {exc}") from exc
        return [DatasetRef(name=n, kind="table") for n in sorted(names)]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        import pandas as pd

        from prospectra.core.sqlutil import ident

        db_cursor = self.connect().cursor()
        try:
            db_cursor.execute(f"SELECT * FROM {ident(ref.name)}")
            columns = [d[0] for d in db_cursor.description]
            rows = db_cursor.fetchall()
        except Exception as exc:
            raise ConnectorError(f"Could not read JDBC table {ref.name!r}: {exc}") from exc
        finally:
            db_cursor.close()

        frame = pd.DataFrame(rows, columns=columns)
        cursor.register("_prospectra_tmp_jdbc", frame)
        try:
            cursor.execute(
                f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _prospectra_tmp_jdbc"
            )
        finally:
            cursor.unregister("_prospectra_tmp_jdbc")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def jdbc_available() -> bool:
    """Is the optional extra installed? (Says nothing about whether a JVM exists.)"""
    try:
        import jaydebeapi  # noqa: F401
    except ImportError:
        return False
    return True
