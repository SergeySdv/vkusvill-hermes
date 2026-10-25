import json

import pytest
from mcp.types import CallToolResult
from typer.testing import CliRunner

from vv.cli import app
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider, provider_data


def test_all_eleven_tools_have_reviewed_schemas():
    assert len(TOOLS) == 11
    assert set(TOOLS.values()) == set(MCPProvider().schemas)


@pytest.mark.parametrize(
    "method,arguments",
    [
        ("barcode", {"barcode": "0012345678901"}),
        ("discounts", {"page": 2, "sort": "name_asc", "kind": "quantity", "vvonly": 0}),
        ("recipes", {"query": "$(touch NEVER)", "id_exclude_allergens_filter": [1, 2]}),
        ("shops", {"page": 2, "id_city_filter": 123}),
        ("orders", {"page": 2}),
        ("favorite", {}),
    ],
)
def test_read_adapters_preserve_arguments(monkeypatch, method, arguments):
    calls = []

    def batch(self, requests):
        calls.extend(requests)
        if method == "barcode":
            return [{"id": 101, "xml_id": 901, "name": "Synthetic", "unit": "шт"}]
        return [{"items": [], "meta": {"page": 2, "filters": ["synthetic"]}}]

    monkeypatch.setattr(MCPProvider, "batch", batch)
    data = getattr(MCPProvider(), method)(**arguments)
    sent = calls[0][1]
    if method == "barcode":
        assert sent["barcode"] == "0012345678901"
        assert data["product_id"] == 101
        assert data["xml_id"] == 901
        assert data["availability"] == "unknown"
    elif method == "recipes":
        assert sent["q"] == "$(touch NEVER)"
        assert sent["id_exclude_allergens_filter"] == [1, 2]
        assert sent["id_category_filter"] == 0
    elif method == "discounts":
        assert sent == {"page": 2, "sort": "name_asc", "type": "quantity", "vvonly": 0}
    else:
        assert sent == arguments


@pytest.mark.parametrize(
    "method,arguments",
    [
        ("barcode", {"barcode": "123"}),
        ("barcode", {"barcode": "0012345678901\n"}),
        ("barcode", {"barcode": "٠" * 13}),
        ("barcode", {"barcode": "$(touch NEVER)"}),
        ("discounts", {"kind": "fake"}),
        ("discounts", {"sort": "fake"}),
        ("discounts", {"vvonly": 2}),
        ("recipes", {"query": "x" * 256}),
        ("recipes", {"sort": "price_asc"}),
        ("recipes", {"id_exclude_allergens_filter": [0]}),
        ("recipes", {"id_category_filter": -1}),
        ("shops", {"q": "not supported"}),
        ("shops", {"id_city_filter": 1000000000}),
        ("orders", {"page": 0}),
        ("orders", {"page": 100000}),
    ],
)
def test_invalid_inputs_never_reach_transport(method, arguments):
    with pytest.raises(VVError) as caught:
        getattr(MCPProvider(), method)(**arguments)
    assert caught.value.code == Code.INVALID_INPUT


@pytest.mark.parametrize("method", ["discounts", "recipes", "shops", "orders"])
@pytest.mark.parametrize("data", [{}, {"items": [1], "meta": {}}, {"items": [], "meta": []}])
def test_paginated_shape_changes_fail_closed(monkeypatch, method, data):
    monkeypatch.setattr(MCPProvider, "batch", lambda *args: [data])
    with pytest.raises(VVError) as caught:
        getattr(MCPProvider(), method)()
    assert caught.value.code == Code.SCHEMA_CHANGED


def test_empty_orders_with_metadata_are_valid(monkeypatch):
    data = {"items": [], "meta": {"page": 1, "total": 0}}
    monkeypatch.setattr(MCPProvider, "batch", lambda *args: [data])
    assert MCPProvider().orders() == data


@pytest.mark.parametrize("orders", [[], [{"id": "synthetic-order"}]])
def test_provider_orders_field_is_normalized_without_losing_metadata(monkeypatch, orders):
    data = {"orders": orders, "meta": {"page": 1, "has_more": False}}
    monkeypatch.setattr(MCPProvider, "batch", lambda *args: [data])
    assert MCPProvider().orders() == {"items": orders, "meta": data["meta"]}
    assert "items" not in data


@pytest.mark.parametrize("data", [
    {"orders": [], "items": [], "meta": {}},
    {"orders": None, "meta": {}}, {"orders": [1], "meta": {}},
    {"orders": []}, {"orders": [], "meta": []},
])
def test_invalid_order_shapes_still_fail(monkeypatch, data):
    monkeypatch.setattr(MCPProvider, "batch", lambda *args: [data])
    with pytest.raises(VVError) as caught:
        MCPProvider().orders()
    assert caught.value.code == Code.SCHEMA_CHANGED


def test_confirmed_empty_favorite_is_explicit():
    result = CallToolResult(content=[], structuredContent={"ok": True, "data": []})
    assert provider_data(result, tool=TOOLS["favorite"]) == {"product": None}


@pytest.mark.parametrize("count", [1, 2])
def test_favorite_array_preserves_every_product_and_field(count):
    data = [{"id": str(index), "name": "Synthetic", "unit": "kg",
             "price": {"synthetic_current": "134"}, "extra": {"synthetic": True}}
            for index in range(count)]
    result = CallToolResult(content=[], structuredContent={"ok": True, "data": data})
    assert provider_data(result, tool=TOOLS["favorite"]) == {"products": data}


@pytest.mark.parametrize("field,value", [
    ("id", 123), ("id", ""), ("name", None), ("unit", None), ("price", []),
])
def test_invalid_favorite_product_fields_fail(field, value):
    product = {"id": "123", "name": "Synthetic", "unit": "kg", "price": {}}
    product[field] = value
    result = CallToolResult(content=[], structuredContent={"ok": True, "data": [product]})
    with pytest.raises(VVError) as caught:
        provider_data(result, tool=TOOLS["favorite"])
    assert caught.value.code == Code.SCHEMA_CHANGED


@pytest.mark.parametrize(
    "tool", [None, *[name for name in TOOLS.values() if name != TOOLS["favorite"]]]
)
def test_empty_array_is_not_accepted_for_other_tools(tool):
    result = CallToolResult(content=[], structuredContent={"ok": True, "data": []})
    with pytest.raises(VVError) as caught:
        provider_data(result, tool=tool)
    assert caught.value.code == Code.SCHEMA_CHANGED


@pytest.mark.parametrize("data", [None, "", [{"id": "unreviewed"}], [1]])
def test_unconfirmed_favorite_shapes_still_fail(data):
    result = CallToolResult(content=[], structuredContent={"ok": True, "data": data})
    with pytest.raises(VVError) as caught:
        provider_data(result, tool=TOOLS["favorite"])
    assert caught.value.code == Code.SCHEMA_CHANGED


@pytest.mark.parametrize("code,expected", [("AUTH_REQUIRED", Code.AUTH_REQUIRED),
                                          ("unexpected", Code.PROVIDER_ERROR)])
def test_empty_favorite_does_not_hide_provider_errors(code, expected):
    result = CallToolResult(content=[], structuredContent={
        "ok": False, "data": [], "error": {"code": code},
    })
    with pytest.raises(VVError) as caught:
        provider_data(result, tool=TOOLS["favorite"])
    assert caught.value.code == expected


@pytest.mark.parametrize("data", [None, [], "", {"items": []}])
def test_unverified_empty_shapes_are_not_silently_normalized(monkeypatch, data):
    def batch(*args):
        return [
            provider_data(CallToolResult(content=[], structuredContent={"ok": True, "data": data}))
        ]

    monkeypatch.setattr(MCPProvider, "batch", batch)
    with pytest.raises(VVError) as caught:
        MCPProvider().orders()
    assert caught.value.code == Code.SCHEMA_CHANGED


@pytest.mark.parametrize(
    "error,expected",
    [
        ({"code": "auth_required"}, Code.AUTH_REQUIRED),
        ({"http_status": 403}, Code.AUTH_REQUIRED),
        ({"code": "invalid_input", "http_status": 404}, Code.NOT_FOUND),
        ({"code": "invalid_input"}, Code.INVALID_INPUT),
        ({"code": "unexpected"}, Code.PROVIDER_ERROR),
    ],
)
def test_provider_errors_are_stable_and_sanitized(error, expected):
    result = CallToolResult(
        content=[],
        structuredContent={"ok": False, "error": {**error, "message": "SECRET_SENTINEL"}},
    )
    with pytest.raises(VVError) as caught:
        provider_data(result)
    assert caught.value.code == expected
    assert "SECRET_SENTINEL" not in caught.value.message


@pytest.mark.parametrize(
    "command",
    [
        ["product", "barcode", "0012345678901"],
        ["discount", "search", "--type", "quantity"],
        ["recipe", "search", "--exclude-allergen", "1", "--exclude-allergen", "2"],
        ["shop", "search", "--city", "123"],
        ["orders", "list", "--page", "2"],
        ["favorite", "show"],
    ],
)
def test_cli_errors_use_json_envelope(tmp_path, monkeypatch, command):
    monkeypatch.setenv("VV_STATE_DIR", str(tmp_path))
    result = CliRunner().invoke(app, [*command, "--json"])
    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "NETWORK_ERROR"
    assert set(envelope) == {"schema_version", "ok", "data", "error", "warnings", "meta"}
