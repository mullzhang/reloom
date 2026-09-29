"""Immutable provenance for generated constraints, including empty connections."""

from dataclasses import dataclass, field
from typing import Literal

from ._validation import Key

type ConstraintKind = Literal["symbolic", "constant_true", "constant_false"]


@dataclass(frozen=True, eq=False, slots=True)
class ConstraintRecord:
    key: Key
    kind: ConstraintKind
    constraint: object = field(repr=False)


@dataclass(frozen=True, eq=False, slots=True)
class ConnectionReport:
    name: str
    left_port: str
    right_port: str
    rows: tuple[ConstraintRecord, ...]


@dataclass(frozen=True, eq=False, slots=True)
class BuildReport:
    name: str
    connections: tuple[ConnectionReport, ...]

    @property
    def constraint_count(self) -> int:
        return sum(len(connection.rows) for connection in self.connections)

    @property
    def constant_true_count(self) -> int:
        return self._count("constant_true")

    @property
    def constant_false_count(self) -> int:
        return self._count("constant_false")

    def _count(self, kind: ConstraintKind) -> int:
        return sum(row.kind == kind for connection in self.connections for row in connection.rows)
