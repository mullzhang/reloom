"""Validation shared by public declarations."""

import re

from .errors import ContractError

type Key = tuple[int | str, ...]


def require_name(value: str, *, field: str, identifier: bool = False) -> None:
    if type(value) is not str or not value.strip():
        raise ContractError("name", f"{field} must be a nonempty built-in string", field=field)
    if identifier and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value) is None:
        raise ContractError("name", f"Invalid {field}: {value!r}", field=field, name=value)


def key_summary(keys: tuple[Key, ...]) -> str:
    return f"{len(keys)} keys {keys[:5]!r}" + (" ..." if len(keys) > 5 else "")
