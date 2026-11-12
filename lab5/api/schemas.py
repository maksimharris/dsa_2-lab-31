from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Amount = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Points = Annotated[int, Field(strict=True, gt=0)]


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: Identifier
    customer_id: Identifier
    store_id: Identifier
    check_number: Identifier
    occurred_at: AwareDatetime


class Purchase(Receipt):
    type: Literal["purchase"]
    amount: Amount


class Return(Receipt):
    type: Literal["return"]


class Redeem(Receipt):
    type: Literal["redeem"]
    amount: Amount
    points: Points
