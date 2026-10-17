from decimal import Decimal

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from vv.cli import app
from vv.constraints import live_report
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider
from vv.models import CartPayload, Request
from vv.normalize import normalize_product
from vv.store import checked_hash


def test_current_product_needs_no_xml_id():
    product = normalize_product({"id": 101, "name": "Synthetic", "unit": "шт"})
    assert product.product_id == 101
    assert product.xml_id is None
    assert product.availability == "unknown"


@pytest.mark.parametrize("size", [1, 20])
def test_current_cart_limits(size):
    payload = CartPayload(products=[{"id": index + 1, "q": "0.01"} for index in range(size)])
    assert len(payload.products) == size


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [{"id": index + 1, "q": 1} for index in range(21)],
        [{"id": 1, "q": 40.01}],
        [{"id": 1, "q": 0.009}],
        [{"id": True, "q": 1}],
        [{"id": 1, "q": 1}, {"id": 1, "q": 2}],
        [{"id": 101, "xml_id": 901, "q": 1}],
    ],
)
def test_current_cart_invalid(lines):
    with pytest.raises(ValidationError):
        CartPayload(products=lines)


def test_legacy_payload_is_readable_but_never_sent():
    payload = CartPayload(products=[{"xml_id": 901, "q": 1}])
    with pytest.raises(VVError) as raised:
        MCPProvider().create_link(payload)
    assert raised.value.code == Code.REVIEW_REQUIRED


def test_different_ids_never_merge_on_old_xml_id():
    request = Request.model_validate(
        {
            "schema_version": 1,
            "constraints": {},
            "items": [
                {"product_id": identifier, "quantity": "1", "unit": "piece"}
                for identifier in (101, 102)
            ],
        }
    )
    products = [
        normalize_product(
            {
                "id": identifier,
                "xml_id": 901,
                "name": "Synthetic",
                "unit": "шт",
                "price": {"current": 100, "currency": "RUB"},
            }
        )
        for identifier in (101, 102)
    ]
    report = live_report(request, products)
    assert [line.id for line in report.payload.products] == [101, 102]
    assert report.goods_total == Decimal("200")


def test_legacy_saved_basket_requires_refresh(service, shopping_request):
    service.import_request("legacy", shopping_request)
    basket = service.check("legacy")
    basket.report.scope = "public_live"
    basket.report.checks = {}
    basket.report.payload = CartPayload(products=[{"xml_id": 901, "q": 1}])
    basket.link = "https://vkusvill.ru/?share_basket=123"
    basket.check_hash = checked_hash(service.store.profile, basket)
    with service.store.transaction() as connection:
        service.store.save(connection, basket)
    assert service.store.show("legacy").link == basket.link
    with pytest.raises(VVError) as raised:
        service.link("legacy", basket.check_hash)
    assert raised.value.code == Code.REVIEW_REQUIRED


def test_personal_discounts_require_confirmation_before_any_network():
    result = CliRunner().invoke(app, ["discount", "personal", "--json"])
    assert result.exit_code == 1
    assert "REVIEW_REQUIRED" in result.stdout


def test_personal_discounts_require_auth():
    provider = MCPProvider()
    provider.auth_context = "public"
    with pytest.raises(VVError) as raised:
        provider.personal_discounts(True)
    assert raised.value.code == Code.AUTH_REQUIRED


def test_personal_discount_exact_call(monkeypatch):
    calls = []
    provider = MCPProvider()
    provider.auth_context = "synthetic-session"

    def batch(requests):
        calls.extend(requests)
        return [{"items": []}]

    monkeypatch.setattr(provider, "batch", batch)
    assert provider.personal_discounts(True) == {"items": []}
    assert calls == [(TOOLS["personal"], {})]
