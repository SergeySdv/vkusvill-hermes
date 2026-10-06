import json

import pytest
from mcp.types import CallToolResult
from typer.testing import CliRunner

from vv.cli import app
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider, provider_data


def test_all_ten_tools_have_reviewed_schemas():
    assert len(TOOLS) == 10
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
