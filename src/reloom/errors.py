"""Structured contract failures and native adapter failures."""

from collections.abc import Mapping
from types import MappingProxyType


class ContractError(ValueError):
    """An inconsistent declaration; ``details`` retains complete diagnostic data."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details: Mapping[str, object] = MappingProxyType(details)


class AdapterError(RuntimeError):
    """Unexpected native preparation/attachment failure, with the original cause."""

    def __init__(self, assembly: str, stage: str) -> None:
        super().__init__(f"Adapter failed to {stage} assembly {assembly!r}; rebuild the assembly")
        self.assembly = assembly
        self.stage = stage
