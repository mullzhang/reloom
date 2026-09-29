"""Public quantities and exact semantic declarations."""

from dataclasses import dataclass, field

from ._validation import require_name
from .indexed import Indexed


@dataclass(frozen=True, slots=True)
class Quantity:
    kind: str
    unit: str
    time_basis: str

    def __post_init__(self) -> None:
        for name, value in (
            ("kind", self.kind),
            ("unit", self.unit),
            ("time_basis", self.time_basis),
        ):
            require_name(value, field=name)


@dataclass(frozen=True, eq=False, slots=True)
class Port[T]:
    name: str
    family: Indexed[T] = field(repr=False)
    quantity: Quantity

    def __post_init__(self) -> None:
        require_name(self.name, field="port name")
