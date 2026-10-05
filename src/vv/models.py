from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

PositiveID = Annotated[StrictInt, Field(gt=0)]
HumanQuantity = Annotated[
    str, Field(pattern=r"^(?:0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$", max_length=32)
]
Money = Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$", max_length=32)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class State(StrEnum):
    DRAFT = "draft"
    CHECKED = "checked"
    LINK_CREATED = "link_created"


class Item(Model):
    product_id: PositiveID
    quantity: HumanQuantity
    unit: Literal["piece", "package", "kg", "g", "l", "ml"]


class Constraints(Model):
    require_availability: bool = False
    currency: Literal["RUB"] = "RUB"
    max_goods_total: Money | None = None
    hard_exclusions: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=100
    )
    preferences: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def unique_exclusions(self):
        if len(set(self.hard_exclusions)) != len(self.hard_exclusions):
            raise ValueError("Duplicate exclusions")
        return self


class Request(Model):
    schema_version: Literal[1]
    items: list[Item] = Field(min_length=1, max_length=1000)
    constraints: Constraints


class CartLine(Model):
    xml_id: PositiveID
    q: Annotated[Decimal, Field(ge=Decimal("0.01"), le=Decimal("40"))]


class CartPayload(Model):
    products: list[CartLine] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_skus(self):
        identifiers = [item.xml_id for item in self.products]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Duplicate SKU: normalize verified units before constructing payload")
        return self


class Finding(Model):
    status: Status
    evidence: str
    blocking: bool = True


class ProductSnapshot(Model):
    product_id: PositiveID
    xml_id: PositiveID
    name: str
    description: str = ""
    price: Annotated[Decimal, Field(ge=0)] | None = None
    currency: str | None = None
    unit: str
    composition: str | None = None
    allergens: str | None = None
    availability: Literal["unknown"] = "unknown"
    source: Literal["https://mcp.vkusvill.ru/mcp"] = "https://mcp.vkusvill.ru/mcp"
    retrieved_at: float


class Report(Model):
    scope: Literal["local_only", "public_live"] = "local_only"
    checked_at: float
    expires_at: float
    catalog_scope: Literal["unverified"] = "unverified"
    goods_total: Decimal | None = None
    checks: dict[str, Finding]
    products: list[ProductSnapshot] = Field(default_factory=list)
    payload: CartPayload | None = None


class Basket(Model):
    name: str
    revision: int = Field(ge=1)
    request: Request
    state: State = State.DRAFT
    report: Report | None = None
    check_hash: str | None = None
    link: str | None = None
    link_attempt: Literal["none", "pending", "unknown"] = "none"
