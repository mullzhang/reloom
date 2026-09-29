"""Identity of one model build and its internal adapter contract."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from .reports import BuildReport

if TYPE_CHECKING:
    from .connections import EqualityPlan


@dataclass(frozen=True, eq=False, slots=True)
class _Prepared:
    native: object = field(repr=False)
    report: BuildReport


class _Adapter[T](Protocol):
    """Internal interface; third-party adapter compatibility is not promised yet."""

    def validate_model(self, model: object) -> None: ...

    def validate_value(self, model: object, value: T) -> None: ...

    def sum_terms(self, terms: Iterable[T]) -> T: ...

    def validate_target(self, model: object, name: str) -> None: ...

    def prepare(
        self, model: object, name: str, plans: tuple[EqualityPlan[T], ...]
    ) -> _Prepared: ...

    def attach(self, model: object, name: str, prepared: _Prepared) -> None: ...


@dataclass(frozen=True, eq=False, slots=True)
class BuildContext[T]:
    """Pass this same instance to every component of one model."""

    model: object = field(repr=False)
    adapter: _Adapter[T]

    def __post_init__(self) -> None:
        self.adapter.validate_model(self.model)
