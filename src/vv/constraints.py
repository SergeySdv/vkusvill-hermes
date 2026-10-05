import time
from decimal import Decimal, localcontext

from vv.errors import Code, VVError
from vv.models import Finding, Report, Request, Status

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
