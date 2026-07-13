# 2026-07-13 (P0): Headless UI smoke — the shell must construct with all workspaces and docks,
# and the log bridge must deliver records into the log view.

import logging

from PySide6.QtWidgets import QDockWidget

from prospectra.ui.main_window import MainWindow


def test_main_window_constructs(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Prospectra"
    tabs = window.centralWidget()
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Flow",
        "Data",
        "Analyze",
        "Dashboards",
    ]
    dock_names = {d.objectName() for d in window.findChildren(QDockWidget)}
    assert {"dock_sources", "dock_buddy", "dock_log"} <= dock_names


def test_log_bridge_delivers_records(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    logger = logging.getLogger("prospectra.test")
    logger.addHandler(window.log_handler)
    try:
        logger.warning("bridge-check-123")
        view = window._log.widget()
        qtbot.waitUntil(lambda: "bridge-check-123" in view.toPlainText(), timeout=2000)
    finally:
        logger.removeHandler(window.log_handler)
