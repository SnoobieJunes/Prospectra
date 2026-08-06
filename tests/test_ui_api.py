# 2026-07-31 (P7): The API playground, driven headless. House style: private attrs are fair game,
# and every widget exposes an explicit seam (`request()`, `set_request()`, `show_response()`) so
# tests read state instead of scraping pixels.

from __future__ import annotations

import pytest

from prospectra.core.http import Auth, HttpRequest, HttpResponse
from prospectra.ui.api.playground import ApiPlaygroundTab
from prospectra.ui.api.request_editor import RequestEditor
from prospectra.ui.api.response_view import ResponseView, tabular_records


@pytest.fixture
def editor(qtbot):
    widget = RequestEditor()
    qtbot.addWidget(widget)
    return widget


def test_request_reflects_typed_values(editor):
    editor._method.setCurrentText("POST")
    editor._url.setText("https://api.test/products")
    editor._params.set_pairs({"page": "2"})
    editor._headers.set_pairs({"X-Tenant": "acme"})
    editor._body_kind.setCurrentIndex(
        list(editor._body_kind.itemData(i) for i in range(editor._body_kind.count())).index("json")
    )
    editor._body.setPlainText('{"q": "shirts"}')

    request = editor.request()
    assert request.method == "POST"
    assert request.url == "https://api.test/products"
    assert request.params == {"page": "2"}
    assert request.headers == {"X-Tenant": "acme"}
    assert request.body_kind == "json" and request.body == '{"q": "shirts"}'


def test_the_displayed_request_masks_the_credential(editor):
    editor._url.setText("https://api.test/x")
    editor._auth_kind.setCurrentIndex(
        list(editor._auth_kind.itemData(i) for i in range(editor._auth_kind.count())).index(
            "bearer"
        )
    )
    editor._token.setText("super-secret-token")
    editor._refresh_curl()

    displayed = editor._curl.toPlainText()
    assert "Authorization: ***" in displayed
    assert "super-secret-token" not in displayed  # the preview cannot leak what it never sees


def test_a_request_round_trips_through_the_editor(editor):
    request = HttpRequest(
        method="PUT",
        url="https://api.test/items/1",
        headers={"X-A": "1"},
        params={"dry": "true"},
        body_kind="json",
        body='{"name": "x"}',
        auth=Auth(kind="header", header="X-API-Key", secret_ref="api:svc"),
    )
    editor.set_request(request)
    restored = editor.request()
    assert restored == request


def test_response_view_shows_status_and_flat_arrays_as_a_table(qtbot):
    view = ResponseView()
    qtbot.addWidget(view)
    response = HttpResponse(
        status=200,
        reason="OK",
        headers={"content-type": "application/json", "Authorization": "Bearer x"},
        text='{"items": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]}',
        json={"items": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]},
        elapsed_ms=12.0,
        size_bytes=48,
    )
    view.show_response(response)
    assert view._pill.text() == "200 OK"
    assert view._tabs.isTabEnabled(view._table_index)  # array of flat objects -> a real table
    assert "Authorization: ***" in view._headers.toPlainText()  # masked even in the headers tab


def test_a_failed_send_is_shown_not_raised(qtbot):
    view = ResponseView()
    qtbot.addWidget(view)
    view.show_response(HttpResponse(error="ConnectError: nobody home"))
    assert view._pill.text() == "FAILED"
    assert "nobody home" in view._meta.text()


def test_tabular_records_refuses_non_tabular_bodies():
    assert tabular_records({"a": 1}) == ([], [])
    assert tabular_records([1, 2, 3]) == ([], [])
    columns, rows = tabular_records([{"a": 1}, {"a": 2}])
    assert columns == ["a"] and rows == [(1,), (2,)]


def test_saving_a_source_requires_a_response_first(qtbot):
    tab = ApiPlaygroundTab()
    qtbot.addWidget(tab)
    tab._editor.set_request(HttpRequest(url="https://api.test/x"))
    with pytest.raises(ValueError, match="send the request once first"):
        tab.mapping()


def test_a_sent_response_can_become_a_mapping(qtbot):
    tab = ApiPlaygroundTab()
    qtbot.addWidget(tab)
    tab._editor.set_request(
        HttpRequest(url="https://api.test/products", headers={"X-Tenant": "acme"})
    )
    tab._last_body = {"data": [{"sku": "A-1", "name": "shirt"}, {"sku": "B-2", "name": "sock"}]}

    mapping = tab.mapping()
    assert mapping.url == "https://api.test/products"
    assert mapping.headers == {"X-Tenant": "acme"}
    assert mapping.records_path == "data"
    assert [c.name for c in mapping.columns] == ["sku", "name"]


def test_saved_requests_load_back_into_the_editor(qtbot):
    tab = ApiPlaygroundTab()
    qtbot.addWidget(tab)
    request = HttpRequest(url="https://api.test/orders", params={"page": "1"})
    tab.set_saved_requests([("id1", "orders", request)])
    tab._load_saved(0)
    assert tab._editor.request().url == "https://api.test/orders"
    assert tab._editor.request().params == {"page": "1"}
