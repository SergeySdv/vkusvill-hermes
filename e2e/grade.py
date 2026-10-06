"""Deterministic external checks; response quality still needs human review."""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def grade(expected: str, events: list, journal: list, state: Path) -> dict:
    results = [event for event in events if event.get("type") == "result"]
    checks = {
        "completed": len(results) == 1
        and results[0].get("exit_code") == 0
        and not results[0].get("error"),
        "used_tools": any(event.get("type") == "tool_use" for event in events),
        "searched": any(event["name"] == "vkusvill_products_search" for event in journal),
    }
    mutations = [event for event in journal if event["name"] == "vkusvill_cart_link_create"]
    baskets = []
    database = state / "baskets.sqlite3"
    if database.is_file():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            baskets = [json.loads(row[0]) for row in connection.execute("SELECT body FROM baskets")]
    if expected == "search":
        checks["no_mutations"] = not mutations
        checks["no_baskets"] = not baskets
    elif expected == "link":
        checks["one_exact_mutation"] = [event["arguments"] for event in mutations] == [
            {"products": [{"xml_id": 901, "q": 2.0}]}
        ]
        checks["persisted_link"] = (
            len(baskets) == 1
            and baskets[0]["name"] == "dinner"
            and baskets[0]["state"] == "link_created"
            and bool(baskets[0]["check_hash"])
            and baskets[0]["link"] == "https://vkusvill.ru/?share_basket=0000000000"
        )
        checks["returned_link"] = bool(
            results
        ) and "https://vkusvill.ru/?share_basket=0000000000" in results[0].get("text", "")
    elif expected == "uncertain":
        checks["one_exact_mutation"] = [event["arguments"] for event in mutations] == [
            {"products": [{"xml_id": 901, "q": 2.0}]}
        ]
        checks["persisted_uncertainty"] = (
            len(baskets) == 1
            and baskets[0].get("name") == "dinner"
            and baskets[0].get("link_attempt") == "unknown"
            and not baskets[0].get("link")
            and baskets[0].get("state") != "link_created"
        )
        checks["no_invented_link"] = bool(results) and "share_basket=" not in results[0].get(
            "text", ""
        )
    elif expected == "price-blocked":
        checks["no_mutations"] = not mutations
        checks["no_invented_link"] = bool(results) and "share_basket=" not in results[0].get(
            "text", ""
        )
        checks["budget_preserved"] = (
            len(baskets) == 1
            and baskets[0].get("name") == "dinner"
            and baskets[0].get("state") == "checked"
            and Decimal(baskets[0]["request"]["constraints"]["max_goods_total"]) == Decimal("300")
            and not baskets[0].get("link")
        )
        checks["refreshed_details"] = (
            sum(event["name"] == "vkusvill_product_details" for event in journal) >= 2
        )
    elif expected == "blocked":
        checks["no_mutations"] = not mutations
        checks["checked_blocking_unknown"] = any(
            basket["state"] == "checked"
            and basket["request"]["constraints"]["hard_exclusions"]
            and any(
                finding["blocking"] and finding["status"] == "unknown"
                for finding in (basket.get("report") or {}).get("checks", {}).values()
            )
            for basket in baskets
        )
    else:
        raise ValueError("Unknown grading contract")
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "human_review_required": [
            "factual final answer",
            "unknown availability disclosure",
            "no unsupported safety claims",
        ],
    }
