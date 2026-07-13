# 2026-07-13 (P1): Data workspace UI coverage — the virtualized grid model pages lazily and the
# DataTab loads a real dataset (grid + profile cards) end-to-end, offscreen.

from prospectra.core.catalog import Catalog
from prospectra.ui.data.data_tab import DataTab
from prospectra.ui.data.grid_model import PAGE_SIZE, DuckTableModel


def test_grid_model_pages_lazily(qtbot):
    calls: list[tuple[int, int]] = []

    def fetch(offset: int, limit: int):
        calls.append((offset, limit))
        return [(i, f"row{i}") for i in range(offset, offset + limit)]

    model = DuckTableModel([("n", "BIGINT"), ("label", "VARCHAR")], 100_000, fetch)
    assert model.rowCount() == 100_000
    # First touch of a cell far into the data triggers exactly one page fetch…
    index = model.index(75_000, 1)
    assert model.data(index) == "…"
    qtbot.waitUntil(lambda: model.data(index) == "row75000", timeout=3000)
    page_offset = (75_000 // PAGE_SIZE) * PAGE_SIZE
    assert calls == [(page_offset, PAGE_SIZE)]
    # …and neighbouring cells in the same page are served from cache.
    assert model.data(model.index(75_001, 0)) == "75001"
    assert calls == [(page_offset, PAGE_SIZE)]


def test_data_tab_shows_dataset(qtbot, tmp_path):
    catalog = Catalog()
    f = tmp_path / "orders.csv"
    f.write_text("region,sales\nWest,10\nEast,20\n", encoding="utf-8")
    (ds,) = catalog.open_file(f)

    tab = DataTab(catalog)
    qtbot.addWidget(tab)
    tab.show_dataset(ds.id)
    qtbot.waitUntil(lambda: "2 rows" in tab._status.text(), timeout=5000)
    qtbot.waitUntil(lambda: tab._grid.model() is not None, timeout=5000)
    assert tab._grid.model().columnCount() == 2
    qtbot.waitUntil(lambda: tab._cards._layout.count() > 1, timeout=5000)  # cards arrived
    catalog.close()
