import pytest

from vv.application import Application
from vv.errors import Code, VVError
from vv.mcp_provider import MCPProvider
from vv.models import Request
from vv.store import Store


@pytest.fixture(autouse=True)
def offline_provider(monkeypatch):
    def unavailable(*args, **kwargs):
        raise VVError(Code.NETWORK_ERROR, "Network disabled in unit tests.")

    monkeypatch.setattr(MCPProvider, "batch", unavailable)


@pytest.fixture
def request_data():
    return {
        "schema_version": 1,
        "items": [{"product_id": 101, "quantity": "2", "unit": "package"}],
        "constraints": {
            "currency": "RUB",
            "max_goods_total": "3000.00",
            "hard_exclusions": ["peanuts"],
            "preferences": ["not spicy"],
        },
    }


@pytest.fixture
def shopping_request(request_data):
    return Request.model_validate(request_data)


@pytest.fixture
def service(tmp_path):
    return Application(Store(tmp_path / "state"), MCPProvider())
