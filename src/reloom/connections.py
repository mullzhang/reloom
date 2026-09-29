"""Validation-only plans for pointwise equalities."""

from dataclasses import dataclass, field

from ._validation import Key, key_summary, require_name
from .errors import ContractError
from .ports import Port


@dataclass(frozen=True, eq=False, slots=True)
class Equality[T]:
    key: Key
    lhs: T = field(repr=False)
    rhs: T = field(repr=False)


@dataclass(frozen=True, eq=False, slots=True)
class EqualityPlan[T]:
    """Keeps its endpoints even when its domain contains no keys."""

    name: str
    left: Port[T]
    right: Port[T]
    rows: tuple[Equality[T], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        require_name(self.name, field="connection name", identifier=True)
        self._validate()
        object.__setattr__(
            self,
            "rows",
            tuple(
                Equality(key, self.left.family[key], self.right.family[key])
                for key in self.left.family.values
            ),
        )

    def _validate(self) -> None:
        a, b = self.left.family, self.right.family
        details: dict[str, object] = {
            "connection": self.name,
            "left_port": self.left.name,
            "right_port": self.right.name,
        }
        if self.left is self.right:
            raise ContractError("connection", "A port cannot connect to itself", **details)
        if a.context is not b.context:
            raise ContractError("context", "Ports must share the same BuildContext", **details)
        if self.left.quantity != self.right.quantity:
            raise ContractError(
                "quantity",
                "Quantity metadata must match exactly",
                **details,
                left_quantity=self.left.quantity,
                right_quantity=self.right.quantity,
            )
        if a.domain.schema != b.domain.schema:
            raise ContractError(
                "schema",
                "Port schemas must match in name and order",
                **details,
                left_schema=a.domain.schema,
                right_schema=b.domain.schema,
            )
        left_only = a.domain.difference(b.domain).tuples()
        right_only = b.domain.difference(a.domain).tuples()
        if left_only or right_only:
            raise ContractError(
                "key_coverage",
                f"Connection coverage mismatch: left_only={key_summary(left_only)}, "
                f"right_only={key_summary(right_only)}",
                **details,
                schema=a.domain.schema,
                left_only=left_only,
                right_only=right_only,
            )
        try:
            a._validate()
            b._validate()
        except ContractError as error:
            raise ContractError(
                error.code, str(error), **(dict(error.details) | details)
            ) from error


def plan_equal[T](left: Port[T], right: Port[T], *, name: str) -> EqualityPlan[T]:
    """Validate all keys and declarations without constructing native constraints."""
    return EqualityPlan(name, left, right)
