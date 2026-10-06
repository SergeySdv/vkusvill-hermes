import json

import pytest

from e2e.support import fixture_server, invoke, read_journal
from vv.errors import VVError
from vv.mcp_provider import ENDPOINT, configured_endpoint


@pytest.fixture
def protocol(tmp_path):
    with fixture_server(tmp_path) as fixture:
        yield fixture


def prepare(protocol, tmp_path, **constraints):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [{"product_id": 101, "quantity": "2", "unit": "package"}],
                "constraints": constraints,
            }
        )
    )
    assert invoke(protocol["env"], "basket", "import", "test", "--file", str(request))["ok"]
    return invoke(protocol["env"], "basket", "check", "test", "--refresh")["data"]


def link(protocol, checked):
    return invoke(
        protocol["env"], "basket", "link", "test", "--checked-hash", checked["check_hash"]
    )


def test_real_sdk_cli_workflow(protocol, tmp_path):
    for arguments in [
        ("doctor", "--live"),
        ("product", "search", "$(touch NEVER)"),
        ("product", "get", "101"),
        ("product", "analogs", "101"),
        ("product", "barcode", "0012345678901"),
        ("discount", "search", "--type", "quantity"),
        ("recipe", "search", "$(touch NEVER)", "--exclude-allergen", "1"),
        ("shop", "search", "--city", "123"),
        ("orders", "list", "--page", "2"),
        ("favorite", "show"),
    ]:
        response = invoke(protocol["env"], *arguments)
        assert response["ok"]
        assert any("SYNTHETIC" in warning for warning in response["warnings"])
    checked = prepare(protocol, tmp_path)
    assert checked["report"]["goods_total"] == "200.00"
    assert checked["report"]["checks"]["availability"]["status"] == "unknown"
    assert link(protocol, checked)["data"]["state"] == "link_created"
    assert link(protocol, checked)["ok"]
    journal = read_journal(protocol["journal"])
    mutations = [event for event in journal if event["name"] == "vkusvill_cart_link_create"]
    assert [event["arguments"] for event in mutations] == [
        {"products": [{"xml_id": 901, "q": 2.0}]}
    ]
    assert journal[1]["arguments"]["q"] == "$(touch NEVER)"
    from vv.mcp_provider import TOOLS

    assert {event["name"] for event in journal} == set(TOOLS.values())
    assert journal[4]["arguments"] == {"barcode": "0012345678901"}
    assert journal[6]["arguments"]["q"] == "$(touch NEVER)"
    assert journal[6]["arguments"]["id_exclude_allergens_filter"] == [1]


@pytest.mark.parametrize(
    "command",
    [
        ("product", "barcode", "0012345678901"),
        ("discount", "search"),
        ("recipe", "search"),
        ("shop", "search"),
        ("orders", "list"),
        ("favorite", "show"),
    ],
)
@pytest.mark.parametrize(
    "setting,code", [("auth_required", "AUTH_REQUIRED"), ("schema_changed", "SCHEMA_CHANGED")]
)
def test_new_tools_fail_closed(protocol, command, setting, code):
    protocol["control"].write_text(json.dumps({setting: True}))
    assert invoke(protocol["env"], *command)["error"]["code"] == code
    if setting == "schema_changed":
        assert not read_journal(protocol["journal"])


@pytest.mark.parametrize(
    "setting,code", [("auth_required", "AUTH_REQUIRED"), ("schema_changed", "SCHEMA_CHANGED")]
)
def test_protocol_errors(protocol, setting, code):
    protocol["control"].write_text(json.dumps({setting: True}))
    assert invoke(protocol["env"], "product", "get", "101")["error"]["code"] == code
    if setting == "schema_changed":
        assert read_journal(protocol["journal"]) == []


def test_price_change_blocks_mutation(protocol, tmp_path):
    checked = prepare(protocol, tmp_path)
    protocol["control"].write_text('{"price": 120}')
    assert link(protocol, checked)["error"]["code"] == "REVIEW_REQUIRED"
    assert all(
        event["name"] != "vkusvill_cart_link_create" for event in read_journal(protocol["journal"])
    )


@pytest.mark.parametrize(
    "constraints", [{"require_availability": True}, {"hard_exclusions": ["peanuts"]}]
)
def test_blocking_unknown(protocol, tmp_path, constraints):
    checked = prepare(protocol, tmp_path, **constraints)
    assert link(protocol, checked)["error"]["code"] == "REVIEW_REQUIRED"
    assert all(
        event["name"] != "vkusvill_cart_link_create" for event in read_journal(protocol["journal"])
    )


def test_uncertain_mutation_cannot_repeat(protocol, tmp_path):
    checked = prepare(protocol, tmp_path)
    protocol["control"].write_text('{"uncertain_link": true}')
    assert link(protocol, checked)["error"]["code"] == "SCHEMA_CHANGED"
    assert link(protocol, checked)["error"]["code"] == "OUTCOME_UNKNOWN"
    assert (
        sum(
            event["name"] == "vkusvill_cart_link_create"
            for event in read_journal(protocol["journal"])
        )
        == 1
    )


def test_endpoint_default_and_guard(monkeypatch):
    monkeypatch.delenv("VV_MCP_TEST_URL", raising=False)
    assert configured_endpoint() == ENDPOINT
    monkeypatch.setenv("VV_MCP_TEST_URL", "http://127.0.0.1:8000/mcp")
    monkeypatch.delenv("VV_TEST_MODE", raising=False)
    with pytest.raises(VVError):
        configured_endpoint()
    monkeypatch.setenv("VV_TEST_MODE", "1")
    assert configured_endpoint() == "http://127.0.0.1:8000/mcp"
    for value in [
        "http://example.com/mcp",
        "http://127.0.0.1@evil.test/mcp",
        "http://localhost/mcp",
        "https://127.0.0.1/mcp",
        "http://127.0.0.1/mcp?x=1",
    ]:
        monkeypatch.setenv("VV_MCP_TEST_URL", value)
        with pytest.raises(VVError):
            configured_endpoint()


def test_paginated_discovery(protocol, tmp_path):
    protocol["control"].write_text('{"pagination": true}')
    checked = prepare(protocol, tmp_path)
    assert link(protocol, checked)["ok"]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_REQUIRED"),
        (403, "AUTH_REQUIRED"),
        (429, "PROVIDER_ERROR"),
        (500, "PROVIDER_ERROR"),
        (503, "PROVIDER_ERROR"),
    ],
)
def test_http_errors_are_sanitized(protocol, status, code):
    protocol["control"].write_text(json.dumps({"http_status": status}))
    response = invoke(protocol["env"], "product", "get", "101")
    assert response["error"]["code"] == code
    assert "SECRET_SENTINEL" not in json.dumps(response)
    assert not read_journal(protocol["journal"])


@pytest.mark.parametrize(
    "settings",
    [
        {"missing_tool": "vkusvill_product_details"},
        {"malformed_result": True},
    ],
)
def test_missing_tool_and_malformed_response(protocol, settings):
    protocol["control"].write_text(json.dumps(settings))
    response = invoke(protocol["env"], "product", "get", "101")
    assert response["error"]["code"] == "SCHEMA_CHANGED"
    assert "SECRET_SENTINEL" not in json.dumps(response)


def test_disconnect_after_mutation_survives_cli_restart(protocol, tmp_path):
    checked = prepare(protocol, tmp_path)
    protocol["control"].write_text('{"drop_after_mutation": true}')
    assert link(protocol, checked)["error"]["code"] == "OUTCOME_UNKNOWN"
    protocol["control"].write_text("{}")
    assert link(protocol, checked)["error"]["code"] == "OUTCOME_UNKNOWN"
    assert (
        sum(
            event["name"] == "vkusvill_cart_link_create"
            for event in read_journal(protocol["journal"])
        )
        == 1
    )


def test_profiles_do_not_share_baskets(protocol, tmp_path):
    prepare(protocol, tmp_path)
    other = {**protocol["env"], "VV_PROFILE": "other"}
    assert invoke(other, "basket", "show", "test")["error"]["code"] == "NOT_FOUND"
    assert invoke(protocol["env"], "basket", "show", "test")["ok"]


def test_discovery_cursor_loop_fails_closed(protocol):
    protocol["control"].write_text('{"pagination": true, "cursor_loop": true}')
    assert invoke(protocol["env"], "product", "get", "101")["error"]["code"] == "SCHEMA_CHANGED"
    assert not read_journal(protocol["journal"])


def test_real_transport_timeout(protocol):
    protocol["control"].write_text('{"delay_seconds": 32}')
    assert invoke(protocol["env"], "product", "get", "101")["error"]["code"] == "NETWORK_ERROR"


def test_tool_error_after_mutation_cannot_retry(protocol, tmp_path):
    checked = prepare(protocol, tmp_path)
    protocol["control"].write_text('{"tool_error_after_mutation": true}')
    assert link(protocol, checked)["error"]["code"] == "OUTCOME_UNKNOWN"
    assert link(protocol, checked)["error"]["code"] == "OUTCOME_UNKNOWN"
    assert (
        sum(
            event["name"] == "vkusvill_cart_link_create"
            for event in read_journal(protocol["journal"])
        )
        == 1
    )
