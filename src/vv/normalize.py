import html
import re
import time

from vv.errors import Code, VVError
from vv.models import ProductSnapshot


def plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", " ", value)).strip()


def normalize_product(data: dict) -> ProductSnapshot:
    try:
        properties = data.get("properties") or []
        if not isinstance(properties, list):
            raise ValueError()
        attributes = {
            item["name"]: plain(item["value"])
            for item in properties
            if isinstance(item, dict) and isinstance(item.get("value"), str)
        }
        price = data.get("price") or {}
        return ProductSnapshot(
            product_id=data["id"],
            xml_id=data["xml_id"],
            name=plain(data["name"]),
            description=plain(data.get("description") or ""),
            price=str(price["current"]) if price.get("current") is not None else None,
            currency=price.get("currency"),
            unit=data.get("unit") or "unknown",
            composition=attributes.get("Состав"),
            allergens=attributes.get("Аллергены по производителям"),
            retrieved_at=time.time(),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VVError(
            Code.SCHEMA_CHANGED, "Product fields no longer match the reviewed contract."
        ) from None
