"""Register complete interfaces before applying any connection constraints."""

from typing import Literal

from ._validation import require_name
from .connections import EqualityPlan
from .context import BuildContext
from .errors import AdapterError, ContractError
from .ports import Port
from .reports import BuildReport


class Assembly[T]:
    def __init__(self, context: BuildContext[T], *, name: str) -> None:
        require_name(name, field="assembly name", identifier=True)
        self._context = context
        self._name = name
        self._ports: dict[str, tuple[Port[T], bool]] = {}
        self._plans: dict[str, EqualityPlan[T]] = {}
        self._used: set[str] = set()
        self._state: Literal["building", "applied", "failed"] = "building"

    @property
    def context(self) -> BuildContext[T]:
        return self._context

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> Literal["building", "applied", "failed"]:
        return self._state

    def _require_building(self) -> None:
        if self._state != "building":
            raise ContractError(
                "assembly",
                f"Assembly {self.name!r} is {self._state}",
                assembly=self.name,
                state=self._state,
            )

    def register(self, port: Port[T], *, required: bool) -> None:
        self._require_building()
        if type(required) is not bool:
            raise ContractError("assembly", "required must be a bool", assembly=self.name)
        if port.family.context is not self.context:
            raise ContractError("context", "Port belongs to another context", port=port.name)
        if port.name in self._ports:
            raise ContractError("assembly", f"Duplicate port name: {port.name!r}", port=port.name)
        self._ports[port.name] = (port, required)

    def add(self, plan: EqualityPlan[T]) -> None:
        self._require_building()
        if plan.name in self._plans:
            raise ContractError(
                "assembly", f"Duplicate connection: {plan.name!r}", connection=plan.name
            )
        plan._validate()
        for port in (plan.left, plan.right):
            registered = self._ports.get(port.name)
            if registered is None or registered[0] is not port:
                raise ContractError("assembly", f"Unregistered port: {port.name!r}", port=port.name)
            if port.name in self._used:
                raise ContractError(
                    "assembly", f"Port already connected: {port.name!r}", port=port.name
                )
        self._plans[plan.name] = plan
        self._used.update((plan.left.name, plan.right.name))

    def validate(self) -> None:
        """Check declarations and target names; leave the native model untouched."""
        self._require_building()
        missing = tuple(
            sorted(
                name
                for name, (_, required) in self._ports.items()
                if required and name not in self._used
            )
        )
        if missing:
            raise ContractError(
                "assembly",
                f"Required ports are unconnected: {missing!r}",
                assembly=self.name,
                ports=missing,
            )
        self.context.adapter.validate_model(self.context.model)
        self.context.adapter.validate_target(self.context.model, self.name)
        for port, _ in self._ports.values():
            try:
                port.family._validate()
            except ContractError as error:
                details = dict(error.details) | {"assembly": self.name, "port": port.name}
                raise ContractError(error.code, str(error), **details) from error
        for plan in self._plans.values():
            plan._validate()

    def apply(self) -> BuildReport:
        """Validate, prepare off-model, then attach once. Never solve the model."""
        self.validate()
        stage = "prepare"
        try:
            prepared = self.context.adapter.prepare(
                self.context.model,
                self.name,
                tuple(self._plans[name] for name in sorted(self._plans)),
            )
            stage = "attach"
            self.context.adapter.attach(self.context.model, self.name, prepared)
        except Exception as error:
            self._state = "failed"
            raise AdapterError(self.name, stage) from error
        self._state = "applied"
        return prepared.report
