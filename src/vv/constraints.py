import time
from decimal import Decimal, localcontext

from pydantic import ValidationError

from vv.errors import Code, VVError
from vv.models import CartPayload, Finding, ProductSnapshot, Report, Request, Status

CHECK_TTL_SECONDS = 900


def normalize_request(request: Request) -> Request:
    grouped = {}
    with localcontext() as context:
        context.prec = 80
        for item in request.items:
            previous = grouped.get(item.product_id)
            if previous is not None and previous.unit != item.unit:
                raise VVError(Code.CONSTRAINT_FAILED, "Same product has incompatible human units.")
            quantity = Decimal(item.quantity)
            if previous is not None:
                quantity += Decimal(previous.quantity)
            grouped[item.product_id] = item.model_copy(
                update={"quantity": format(quantity.normalize(), "f")}
            )
    if len(grouped) > 20:
        raise VVError(Code.CONSTRAINT_FAILED, "A basket may contain at most 20 distinct products.")
    return Request.model_validate(
        {**request.model_dump(), "items": [grouped[key].model_dump() for key in sorted(grouped)]}
    )


def local_report() -> Report:
    now = time.time()
    unknown = {
        "provider_ids": "Product id to xml_id mapping has not been verified.",
        "quantity": "Human units are not verified provider quantities; q is unknown.",
        "budget": "Prices and delivery costs are unknown.",
        "hard_exclusions": "No verified composition evidence.",
        "availability": "No authenticated address/catalog context.",
    }
    return Report(
        checked_at=now,
        expires_at=now + CHECK_TTL_SECONDS,
        checks={
            "local_shape": Finding(
                status=Status.PASS, evidence="Local schema and line count valid."
            ),
            **{
                name: Finding(status=Status.UNKNOWN, evidence=evidence)
                for name, evidence in unknown.items()
            },
        },
    )


def live_report(request: Request, products: list[ProductSnapshot]) -> Report:
    with localcontext() as context:
        context.prec = 80
        return _live_report(request, products)


def _live_report(request: Request, products: list[ProductSnapshot]) -> Report:
    if [product.product_id for product in products] != [item.product_id for item in request.items]:
        raise VVError(Code.SCHEMA_CHANGED, "Refreshed products do not match the basket.")
    quantities = {}
    sale_bases = {}
    total = Decimal("0")
    price_known = True
    quantity_status = Status.PASS
    for item, product in zip(request.items, products, strict=True):
        sale_basis = (product.unit, product.price, product.currency)
        if product.xml_id in sale_bases and sale_bases[product.xml_id] != sale_basis:
            raise VVError(Code.SCHEMA_CHANGED, "One SKU has conflicting sale units or prices.")
        sale_bases[product.xml_id] = sale_basis
        quantity = Decimal(item.quantity)
        if product.unit == "шт" and item.unit in ("piece", "package"):
            if quantity != quantity.to_integral_value():
                quantity_status = Status.FAIL
        elif product.unit == "кг" and item.unit in ("kg", "g"):
            if item.unit == "g":
                quantity /= 1000
            if quantity != quantity.quantize(Decimal("0.01")):
                quantity_status = Status.FAIL
        else:
            quantity_status = Status.UNKNOWN if quantity_status != Status.FAIL else Status.FAIL
        quantities[product.xml_id] = quantities.get(product.xml_id, Decimal("0")) + quantity
        if product.price is None or product.currency != "RUB":
            price_known = False
        else:
            total += product.price * quantity
    payload = None
    if quantity_status == Status.PASS:
        try:
            payload = CartPayload(
                products=[
                    {"xml_id": identifier, "q": quantity}
                    for identifier, quantity in quantities.items()
                ]
            )
        except ValidationError:
            quantity_status = Status.FAIL
    goods_total = total.quantize(Decimal("0.01")) if price_known and payload else None
    exclusions = request.constraints.hard_exclusions
    exclusion_status = Status.PASS if not exclusions else Status.UNKNOWN
    for product in products:
        evidence = ((product.composition or "") + " " + (product.allergens or "")).casefold()
        if any(exclusion.casefold() in evidence for exclusion in exclusions):
            exclusion_status = Status.FAIL
    budget_status = Status.UNKNOWN if goods_total is None else Status.PASS
    budget = request.constraints.max_goods_total
    if budget is not None and goods_total is not None and goods_total > Decimal(budget):
        budget_status = Status.FAIL
    now = time.time()
    return Report(
        scope="public_live",
        checked_at=now,
        expires_at=now + CHECK_TTL_SECONDS,
        goods_total=goods_total,
        products=products,
        payload=payload,
        checks={
            "provider_ids": Finding(status=Status.PASS, evidence="ids resolved from MCP details."),
            "quantity": Finding(
                status=quantity_status,
                evidence="Use whole sale units for шт; kg/g only for кг, at 0.01 kg precision.",
            ),
            "budget": Finding(
                status=budget_status,
                evidence="Public goods estimate in RUB; delivery and regional prices unverified.",
                blocking=budget is not None,
            ),
            "hard_exclusions": Finding(
                status=exclusion_status,
                evidence="Missing ingredient text does not establish safety.",
                blocking=bool(exclusions),
            ),
            "availability": Finding(
                status=Status.UNKNOWN,
                evidence="Public catalog has no verified delivery address or stock.",
                blocking=request.constraints.require_availability,
            ),
        },
    )


def comparable_report(report: Report) -> dict:
    value = report.model_dump(mode="json", exclude={"checked_at", "expires_at"})
    for product in value["products"]:
        product.pop("retrieved_at", None)
    return value
