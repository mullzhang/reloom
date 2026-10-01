"""Total, immutable key mappings whose native values remain opaque to the core."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import Literal

from relindex import Relation

from ._validation import Key, key_summary
from .context import BuildContext
from .errors import ContractError


@dataclass(frozen=True, eq=False, slots=True)
class _Values[T](Mapping[Key, T]):
    domain: Relation
    keys_in_order: tuple[Key, ...]
    data: Mapping[Key, T] = field(repr=False)

    def __getitem__(self, key: Key) -> T:
        if key not in self.domain:
            raise KeyError(key)
        return self.data[key]

    def __iter__(self) -> Iterator[Key]:
        return iter(self.keys_in_order)

    def __len__(self) -> int:
        return len(self.keys_in_order)


@dataclass(frozen=True, eq=False, slots=True)
class Indexed[T]:
    """Exactly one native value per domain key; no missing-value imputation."""

    domain: Relation
    values: Mapping[Key, T] = field(repr=False)
    context: BuildContext[T] = field(repr=False)

    def __post_init__(self) -> None:
        snapshot = dict(self.values)
        actual = Relation(snapshot.keys(), schema=self.domain.schema)
        missing = self.domain.difference(actual).tuples()
        extra = actual.difference(self.domain).tuples()
        if missing or extra:
            raise ContractError(
                "key_coverage",
                f"Key coverage mismatch: missing={key_summary(missing)}, "
                f"extra={key_summary(extra)}",
                schema=self.domain.schema,
                missing=missing,
                extra=extra,
            )
        object.__setattr__(
            self, "values", _Values(self.domain, self.domain.tuples(), MappingProxyType(snapshot))
        )
        self._validate()

    def __getitem__(self, key: Key) -> T:
        return self.values[key]

    def _validate(self) -> None:
        self.context.adapter.validate_model(self.context.model)
        # The optional factory scopes reusable backend state to this pass.
        # Adapters implementing only validate_value retain the original contract.
        factory = getattr(self.context.adapter, "value_validator", None)
        validate_value: Callable[[T], None]
        if factory is None:
            validate_value = partial(self.context.adapter.validate_value, self.context.model)
        else:
            validate_value = factory(self.context.model)
        for key, value in self.values.items():
            try:
                validate_value(value)
            except ContractError as error:
                details = dict(error.details)
                details.update(key=key, schema=self.domain.schema)
                raise ContractError(error.code, f"{error} at key {key!r}", **details) from error

    def rename(self, mapping: Mapping[str, str]) -> Indexed[T]:
        """Rename columns without changing keys, values, or context."""
        return Indexed(self.domain.rename(mapping), self.values, self.context)

    def reorder(self, *columns: str) -> Indexed[T]:
        """Permute all columns; dropping or repeating columns is an error."""
        if len(columns) != len(self.domain.schema) or set(columns) != set(self.domain.schema):
            raise ContractError(
                "schema",
                "reorder requires a permutation of every column",
                columns=columns,
                schema=self.domain.schema,
            )
        domain = self.domain.project(*columns)
        positions = tuple(self.domain.schema.index(column) for column in columns)
        values = {tuple(key[i] for i in positions): value for key, value in self.values.items()}
        return Indexed(domain, values, self.context)


def sum_over[T](
    source: Indexed[T],
    *columns: str,
    over: Relation,
    empty: Literal["zero", "error"],
) -> Indexed[T]:
    """Sum full source keys over an explicit domain, with an explicit empty policy."""
    if empty not in ("zero", "error"):
        raise ContractError("empty_group", f"Unsupported empty-group policy: {empty!r}")
    groups = source.domain.group_by(*columns, over=over)
    empty_keys = tuple(key for key, rows in groups.items() if not rows)
    if empty == "error" and empty_keys:
        raise ContractError(
            "empty_group",
            f"Empty source groups: {key_summary(empty_keys)}",
            keys=empty_keys,
            schema=over.schema,
        )
    source._validate()
    values = {
        key: source.context.adapter.sum_terms(source.values[row] for row in rows)
        for key, rows in groups.items()
    }
    return Indexed(over, values, source.context)
