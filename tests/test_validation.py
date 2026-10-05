import pytest
from pydantic import ValidationError

from vv.constraints import normalize_request
from vv.errors import Code, VVError
from vv.models import CartPayload, Request


@pytest.mark.parametrize("quantity", ["0.01", "40", "1.25"])
def test_provider_quantity_boundaries(quantity):
    payload = CartPayload(products=[{"xml_id": 901, "q": quantity}])
    assert str(payload.products[0].q) == quantity


@pytest.mark.parametrize("quantity", ["0", "-1", "0.009", "40.001", "NaN", "Infinity", True])
def test_invalid_provider_quantity(quantity):
    with pytest.raises(ValidationError):
        CartPayload(products=[{"xml_id": 901, "q": quantity}])


@pytest.mark.parametrize("size", [1, 20])
def test_cart_line_boundaries(size):
    assert (
        len(
            CartPayload(
                products=[{"xml_id": index + 1, "q": "1"} for index in range(size)]
            ).products
        )
        == size
    )


@pytest.mark.parametrize("size", [0, 21])
def test_cart_line_limits(size):
    with pytest.raises(ValidationError):
        CartPayload(products=[{"xml_id": index + 1, "q": "1"} for index in range(size)])


def test_duplicate_skus_rejected():
    with pytest.raises(ValidationError):
        CartPayload(products=[{"xml_id": 1, "q": 1}, {"xml_id": 1, "q": 1}])


@pytest.mark.parametrize("extra", [{"xml_id": 901}, {"price": 99}, {"q": "2"}])
def test_agent_cannot_import_provider_facts(request_data, extra):
    request_data["items"][0].update(extra)
    with pytest.raises(ValidationError):
        Request.model_validate(request_data)


@pytest.mark.parametrize("product_id", [True, "101", 0, -1, 1.5])
def test_id_is_positive_strict_integer(request_data, product_id):
    request_data["items"][0]["product_id"] = product_id
    with pytest.raises(ValidationError):
        Request.model_validate(request_data)


def test_product_id_is_not_xml_id():
    with pytest.raises(ValidationError):
        CartPayload(products=[{"product_id": 101, "q": "1"}])


def test_duplicate_human_quantities_merge_exactly(request_data):
    request_data["items"] *= 2
    normalized = normalize_request(Request.model_validate(request_data))
    assert len(normalized.items) == 1
    assert normalized.items[0].quantity == "4"


def test_cannot_merge_different_units(request_data):
    request_data["items"].append({"product_id": 101, "quantity": "2", "unit": "kg"})
    with pytest.raises(VVError) as caught:
        normalize_request(Request.model_validate(request_data))
    assert caught.value.code == Code.CONSTRAINT_FAILED


def test_normalized_line_limit(request_data):
    request_data["items"] = [
        {"product_id": index + 1, "quantity": "1", "unit": "piece"} for index in range(21)
    ]
    with pytest.raises(VVError) as caught:
        normalize_request(Request.model_validate(request_data))
    assert caught.value.code == Code.CONSTRAINT_FAILED


def test_human_grams_are_not_provider_q(request_data):
    request_data["items"][0].update(quantity="500", unit="g")
    assert normalize_request(Request.model_validate(request_data)).items[0].quantity == "500"
