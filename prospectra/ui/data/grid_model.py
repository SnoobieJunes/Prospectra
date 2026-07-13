# 2026-07-13 (P1): Virtualized table model — reports the full row count up front but fetches
# 500-row pages lazily through a pluggable fetcher (run on the thread pool), with an LRU page
# cache. Why: the P1 acceptance criterion is browsing 1M rows without freezing the GUI; loading
# cells render as "…" until their page lands and dataChanged repaints them.

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from prospectra.ui.workers import run_in_pool

_AnyIndex = QModelIndex | QPersistentModelIndex

PAGE_SIZE = 500
_CACHE_PAGES = 40

PageFetcher = Callable[[int, int], list[tuple[Any, ...]]]  # (offset, limit) -> rows


class DuckTableModel(QAbstractTableModel):
    def __init__(
        self,
        columns: list[tuple[str, str]],
        row_count: int,
        fetch_page: PageFetcher,
    ) -> None:
        super().__init__()
        self._columns = columns
        self._row_count = row_count
        self._fetch = fetch_page
        self._pages: OrderedDict[int, list[tuple[Any, ...]]] = OrderedDict()
        self._inflight: set[int] = set()

    # -- Qt model interface ----------------------------------------------------------

    def rowCount(self, parent: _AnyIndex = QModelIndex()) -> int:  # noqa: B008 - Qt API
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent: _AnyIndex = QModelIndex()) -> int:  # noqa: B008 - Qt API
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            name, dtype = self._columns[section]
            return f"{name}\n{dtype}"
        return section + 1

    def data(self, index: _AnyIndex, role: int = 0) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        page, offset = divmod(index.row(), PAGE_SIZE)
        rows = self._pages.get(page)
        if rows is None:
            self._request(page)
            return "…"
        self._pages.move_to_end(page)  # LRU touch
        value = rows[offset][index.column()] if offset < len(rows) else None
        return "" if value is None else str(value)

    # -- paging ------------------------------------------------------------------------

    def _request(self, page: int) -> None:
        if page in self._inflight:
            return
        self._inflight.add(page)
        run_in_pool(
            self._fetch,
            page * PAGE_SIZE,
            PAGE_SIZE,
            on_result=partial(self._store, page),
            on_error=partial(self._page_failed, page),
        )

    def _page_failed(self, page: int, _message: str) -> None:
        self._inflight.discard(page)

    def _store(self, page: int, rows: list[tuple[Any, ...]]) -> None:
        self._inflight.discard(page)
        self._pages[page] = rows
        while len(self._pages) > _CACHE_PAGES:
            self._pages.popitem(last=False)
        first = page * PAGE_SIZE
        last = min(first + PAGE_SIZE, self._row_count) - 1
        if last >= first:
            self.dataChanged.emit(self.index(first, 0), self.index(last, len(self._columns) - 1))
