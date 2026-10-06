import json
import sqlite3

import pytest

from e2e.grade import grade


def completed():
    return [
        {"type": "tool_use", "name": "terminal"},
        {"type": "result", "exit_code": 0, "text": "done"},
    ]


def search():
    return [{"name": "vkusvill_products_search", "arguments": {"q": "milk"}}]


def test_prose_is_not_success(tmp_path):
    assert not grade("search", [{"type": "text", "text": "Success!"}], [], tmp_path)["passed"]
    assert not grade("link", completed(), search(), tmp_path)["passed"]
    assert not grade("blocked", completed(), search(), tmp_path)["passed"]


def test_search_no_mutation(tmp_path):
    assert grade("search", completed(), search(), tmp_path)["passed"]
    journal = [*search(), {"name": "vkusvill_cart_link_create", "arguments": {}}]
    assert not grade("search", completed(), journal, tmp_path)["passed"]


def test_failed_result_not_accepted(tmp_path):
    events = completed()
    events[-1]["exit_code"] = 1
    assert not grade("search", events, search(), tmp_path)["passed"]


def test_link_requires_exact_payload_and_saved_state(tmp_path):
    with sqlite3.connect(tmp_path / "baskets.sqlite3") as connection:
        connection.execute("CREATE TABLE baskets(body TEXT)")
        connection.execute(
            "INSERT INTO baskets VALUES (?)",
            (
                json.dumps(
                    {
                        "name": "dinner",
                        "state": "link_created",
                        "check_hash": "reviewed",
                        "link": "https://vkusvill.ru/?share_basket=0000000000",
                    }
                ),
            ),
        )
    events = completed()
    events[-1]["text"] = "https://vkusvill.ru/?share_basket=0000000000"
    journal = [
        *search(),
        {"name": "vkusvill_cart_link_create", "arguments": {"products": [{"xml_id": 901, "q": 2}]}},
    ]
    assert grade("link", events, journal, tmp_path)["passed"]
    journal[-1]["arguments"]["products"][0]["xml_id"] = 101
    assert not grade("link", events, journal, tmp_path)["passed"]


def test_unknown_contract_rejected(tmp_path):
    with pytest.raises(ValueError):
        grade("invented", [], [], tmp_path)


@pytest.mark.parametrize("expected", ["uncertain", "price-blocked"])
def test_new_contracts_reject_prose_without_state(tmp_path, expected):
    assert not grade(expected, completed(), search(), tmp_path)["passed"]


def test_uncertain_contract_rejects_duplicate_mutations(tmp_path):
    with sqlite3.connect(tmp_path / "baskets.sqlite3") as connection:
        connection.execute("CREATE TABLE baskets(body TEXT)")
        connection.execute(
            "INSERT INTO baskets VALUES (?)",
            (
                json.dumps(
                    {
                        "name": "dinner",
                        "state": "checked",
                        "link_attempt": "unknown",
                        "link": None,
                    }
                ),
            ),
        )
    mutation = {
        "name": "vkusvill_cart_link_create",
        "arguments": {"products": [{"xml_id": 901, "q": 2}]},
    }
    assert grade("uncertain", completed(), [*search(), mutation], tmp_path)["passed"]
    assert not grade("uncertain", completed(), [*search(), mutation, mutation], tmp_path)["passed"]


def test_price_contract_preserves_budget(tmp_path):
    basket = {
        "name": "dinner",
        "state": "checked",
        "link": None,
        "request": {"constraints": {"max_goods_total": "300"}},
    }
    with sqlite3.connect(tmp_path / "baskets.sqlite3") as connection:
        connection.execute("CREATE TABLE baskets(body TEXT)")
        connection.execute("INSERT INTO baskets VALUES (?)", (json.dumps(basket),))
    journal = [*search(), *[{"name": "vkusvill_product_details", "arguments": {"id": 101}}] * 2]
    assert grade("price-blocked", completed(), journal, tmp_path)["passed"]
    basket["request"]["constraints"]["max_goods_total"] = "500"
    with sqlite3.connect(tmp_path / "baskets.sqlite3") as connection:
        connection.execute("UPDATE baskets SET body=?", (json.dumps(basket),))
    assert not grade("price-blocked", completed(), journal, tmp_path)["passed"]
