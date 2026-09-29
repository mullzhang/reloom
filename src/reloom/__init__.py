"""Indexed expressions and explicit connection contracts, without solver imports."""

from .assembly import Assembly
from .connections import Equality, EqualityPlan, plan_equal
from .context import BuildContext
from .errors import AdapterError, ContractError
from .indexed import Indexed, sum_over
from .ports import Port, Quantity
from .reports import BuildReport, ConnectionReport, ConstraintRecord

__all__ = [
    "AdapterError",
    "Assembly",
    "BuildContext",
    "BuildReport",
    "ConnectionReport",
    "ConstraintRecord",
    "ContractError",
    "Equality",
    "EqualityPlan",
    "Indexed",
    "Port",
    "Quantity",
    "plan_equal",
    "sum_over",
]
