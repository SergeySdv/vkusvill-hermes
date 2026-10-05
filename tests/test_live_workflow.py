import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from mcp.types import CallToolResult

from vv.application import Application
from vv.constraints import live_report
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider, provider_data, valid_link
from vv.models import CartPayload, ProductSnapshot, State, Status
from vv.normalize import normalize_product
from vv.store import Store


@pytest.fixture
def public_request(shopping_request):
    shopping_request.constraints.hard_exclusions = []
    return shopping_request


@pytest.fixture
def product():
    return ProductSnapshot(
        product_id=101,
        xml_id=901,
        name="Synthetic test item",
        price="100",
        currency="RUB",
        unit="шт",
        composition="Synthetic ingredients",
        retrieved_at=1,
    )


class TestProvider:
    __test__ = False

    def __init__(self, product):
        self.product = product
        self.links = 0
        self.payload = None
        self.failure = None

    def refresh(self, request):
        return [self.product.model_copy(deep=True)]

    def create_link(self, payload):
        self.links += 1
        self.payload = payload
        if self.failure:
            raise self.failure
        return "https://vkusvill.ru/?share_basket=123"


@pytest.fixture
def live_service(tmp_path, product):
    return Application(Store(tmp_path / "state"), TestProvider(product))


def prepare(service, request):
    service.import_request("dinner", request)
    return service.check("dinner", refresh=True)


def test_complete_public_workflow_and_dedup(live_service, public_request):
    checked = prepare(live_service, public_request)
    assert checked.report.goods_total == Decimal("200")
    assert checked.report.checks["availability"].status == Status.UNKNOWN
    assert not checked.report.checks["availability"].blocking
    linked = live_service.link("dinner", checked.check_hash)
    assert linked.state == State.LINK_CREATED
    assert linked.link == "https://vkusvill.ru/?share_basket=123"
    assert live_service.provider.payload.products[0].xml_id == 901
    assert live_service.provider.links == 1
    assert live_service.link("dinner", checked.check_hash) == linked
    assert live_service.provider.links == 1


@pytest.mark.parametrize("change", ["price", "xml_id", "unit", "composition"])
def test_live_changes_require_review(live_service, public_request, change):
    checked = prepare(live_service, public_request)
    setattr(
        live_service.provider.product,
        change,
        {"price": Decimal("120"), "xml_id": 999, "unit": "кг", "composition": "Changed"}[change],
    )
    with pytest.raises(VVError) as caught:
        live_service.link("dinner", checked.check_hash)
    assert caught.value.code == Code.REVIEW_REQUIRED
    assert live_service.provider.links == 0


@pytest.mark.parametrize("constraint", ["availability", "budget", "exclusion"])
def test_required_checks_block(live_service, public_request, constraint):
    if constraint == "availability":
        public_request.constraints.require_availability = True
    elif constraint == "budget":
        public_request.constraints.max_goods_total = "1"
    else:
        public_request.constraints.hard_exclusions = ["peanuts"]
    checked = prepare(live_service, public_request)
    with pytest.raises(VVError) as caught:
        live_service.link("dinner", checked.check_hash)
    assert caught.value.code in (Code.REVIEW_REQUIRED, Code.CONSTRAINT_FAILED)
    assert live_service.provider.links == 0


def test_unknown_price_not_zero(product, public_request):
    product.price = None
    report = live_report(public_request, [product])
    assert report.goods_total is None
    assert report.checks["budget"].status == Status.UNKNOWN


def test_forbidden_ingredient_fails(product, public_request):
    product.composition = "contains PEANUTS"
    public_request.constraints.hard_exclusions = ["peanuts"]
    assert live_report(public_request, [product]).checks["hard_exclusions"].status == Status.FAIL


@pytest.mark.parametrize(
    "unit,quantity,provider_unit,status,q",
    [
        ("package", "2", "шт", Status.PASS, Decimal("2")),
        ("piece", "0.5", "шт", Status.FAIL, None),
        ("g", "500", "кг", Status.PASS, Decimal("0.5")),
        ("kg", "0.001", "кг", Status.FAIL, None),
        ("kg", "40.01", "кг", Status.FAIL, None),
        ("package", "2", "unknown", Status.UNKNOWN, None),
        ("ml", "500", "шт", Status.UNKNOWN, None),
    ],
)
def test_quantity_mapping(product, public_request, unit, quantity, provider_unit, status, q):
    public_request.items[0].unit = unit
    public_request.items[0].quantity = quantity
    product.unit = provider_unit
    report = live_report(public_request, [product])
    assert report.checks["quantity"].status == status
    if q is not None:
        assert report.payload.products[0].q == q


def test_unknown_mutation_blocks_retry_and_edits(live_service, public_request):
    checked = prepare(live_service, public_request)
    live_service.provider.failure = VVError(Code.OUTCOME_UNKNOWN, "timeout")
    with pytest.raises(VVError):
        live_service.link("dinner", checked.check_hash)
    assert live_service.store.show("dinner").link_attempt == "unknown"
    operations = [
        lambda: live_service.link("dinner", checked.check_hash),
        lambda: live_service.check("dinner", refresh=True),
        lambda: live_service.import_request("dinner", public_request),
    ]
    for operation in operations:
        with pytest.raises(VVError) as caught:
            operation()
        assert caught.value.code == Code.OUTCOME_UNKNOWN
    assert live_service.provider.links == 1


def test_pending_blocks_concurrent_link(live_service, public_request, monkeypatch):
    checked = prepare(live_service, public_request)
    original = live_service.provider.create_link

    def nested(payload):
        with pytest.raises(VVError) as caught:
            live_service.link("dinner", checked.check_hash)
        assert caught.value.code == Code.OUTCOME_UNKNOWN
        return original(payload)

    monkeypatch.setattr(live_service.provider, "create_link", nested)
    live_service.link("dinner", checked.check_hash)
    assert live_service.provider.links == 1


def test_product_normalization_preserves_distinct_ids():
    snapshot = normalize_product(
        {
            "id": 101,
            "xml_id": 901,
            "name": "Milk&nbsp;test",
            "unit": "шт",
            "price": {"current": 100, "currency": "RUB"},
            "properties": [{"name": "Состав", "value": "milk<br>test"}],
        }
    )
    assert (snapshot.product_id, snapshot.xml_id) == (101, 901)
    assert snapshot.price == Decimal("100")
    assert snapshot.availability == "unknown"


@pytest.mark.parametrize(
    "link",
    [
        "http://vkusvill.ru/?share_basket=123",
        "https://vkusvill.ru.evil.invalid/?share_basket=123",
        "https://evil.invalid/?share_basket=123",
        "https://user@vkusvill.ru/?share_basket=123",
        "https://vkusvill.ru/other?share_basket=123",
        "javascript:alert(1)",
        None,
    ],
)
def test_reject_unsafe_provider_links(link):
    with pytest.raises(VVError):
        valid_link(link)


def test_provider_error_envelope_is_not_success():
    result = CallToolResult(
        content=[], structuredContent={"ok": False, "error": {"code": "AUTH_REQUIRED"}}
    )
    with pytest.raises(VVError) as caught:
        provider_data(result)
    assert caught.value.code == Code.AUTH_REQUIRED


def test_live_sdk_boundary_checks_schema_before_call(monkeypatch):
    provider = MCPProvider()
    calls = []

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield ("read", "write", None)

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self, cursor=None):
            return SimpleNamespace(
                tools=[SimpleNamespace(name=TOOLS["link"], inputSchema={"required": ["new"]})],
                nextCursor=None,
            )

        async def call_tool(self, *args):
            calls.append(args)

    monkeypatch.setattr("vv.mcp_provider.streamable_http_client", transport)
    monkeypatch.setattr("vv.mcp_provider.ClientSession", Session)
    with pytest.raises(VVError) as caught:
        asyncio.run(provider._batch([(TOOLS["link"], {"products": []})]))
    assert caught.value.code == Code.SCHEMA_CHANGED
    assert calls == []


def test_mcp_create_link_uses_xml_id_and_numeric_quantity(monkeypatch):
    provider = MCPProvider()
    calls = []

    def batch(arguments):
        calls.extend(arguments)
        return [{"link": "https://vkusvill.ru/?share_basket=123"}]

    monkeypatch.setattr(provider, "batch", batch)
    provider.create_link(CartPayload(products=[{"xml_id": 901, "q": "0.5"}]))
    assert calls == [(TOOLS["link"], {"products": [{"xml_id": 901, "q": 0.5}]})]


def test_nested_transport_error_is_sanitized():
    from vv.mcp_provider import leaves, transport_error

    error = ExceptionGroup("secret", [httpx.ReadTimeout("secret")])
    mapped = transport_error(leaves(error)[0], side_effect=True)
    assert mapped.code == Code.OUTCOME_UNKNOWN
    assert "secret" not in mapped.message


def test_same_sku_merged_before_quantity_limit(product, public_request):
    second = product.model_copy(update={"product_id": 102})
    public_request.items[0].quantity = "20"
    public_request.items.append(public_request.items[0].model_copy(update={"product_id": 102}))
    report = live_report(public_request, [product, second])
    assert len(report.payload.products) == 1
    assert report.payload.products[0].q == Decimal("40")
    public_request.items[1].quantity = "21"
    report = live_report(public_request, [product, second])
    assert report.payload is None
    assert report.checks["quantity"].status == Status.FAIL


def test_conflicting_sku_sale_bases_rejected(product, public_request):
    second = product.model_copy(update={"product_id": 102, "price": Decimal("150")})
    public_request.items.append(public_request.items[0].model_copy(update={"product_id": 102}))
    with pytest.raises(VVError) as caught:
        live_report(public_request, [product, second])
    assert caught.value.code == Code.SCHEMA_CHANGED


def test_refresh_race_does_not_send_link(live_service, public_request, monkeypatch):
    checked = prepare(live_service, public_request)
    original = live_service.provider.refresh

    def racing(request):
        live_service.import_request("dinner", public_request)
        return original(request)

    monkeypatch.setattr(live_service.provider, "refresh", racing)
    with pytest.raises(VVError) as caught:
        live_service.link("dinner", checked.check_hash)
    assert caught.value.code == Code.REVIEW_REQUIRED
    assert live_service.provider.links == 0


def test_malformed_unicode_hash_is_review_required(live_service, public_request):
    prepare(live_service, public_request)
    with pytest.raises(VVError) as caught:
        live_service.link("dinner", "не-хеш")
    assert caught.value.code == Code.REVIEW_REQUIRED
