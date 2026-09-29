import pytest

pyo = pytest.importorskip("pyomo.environ")
pytest.importorskip("highspy")
from examples import network, supply_chain  # noqa: E402

from .reference_models import supply_model  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.solver]


@pytest.mark.parametrize(
    "scenario,expected", [("normal", 26), ("unreachable", None), ("stock", 14)]
)
def test_supply_scenarios_and_handwritten_solver_results(scenario, expected):
    data = supply_chain.sample_data(scenario)
    composed, report = supply_chain.build_model(data)
    assert report.constraint_count == 4
    for model in (composed, supply_model(data)):
        status = supply_chain.solve(model)
        if expected is None:
            assert status == "infeasible"
        else:
            assert status == "optimal"
            assert pyo.value(model.objective) == pytest.approx(expected)
            assert pyo.value(model.production.q["F2", "P1"]) == pytest.approx(0)


def test_network_including_isolated_node():
    model, report = network.build_model()
    assert supply_chain.solve(model) == "optimal"
    assert pyo.value(model.objective) == pytest.approx(9)
    assert report.constraint_count == 4
    assert report.constant_true_count == 1
    isolated = next(row for row in report.connections[0].rows if row.key == ("I",))
    assert isolated.kind == "constant_true"


@pytest.mark.parametrize("rhs,expected", [(0, "optimal"), (1, "infeasible")])
def test_constant_equality_reaches_solver(rhs, expected):
    from relindex import Relation

    from reloom import Assembly, BuildContext, Indexed, Port, Quantity, plan_equal
    from reloom.adapters.pyomo import PyomoAdapter

    model = pyo.ConcreteModel()
    model.x = pyo.Var(bounds=(0, 1))
    model.objective = pyo.Objective(expr=model.x)
    context = BuildContext(model, PyomoAdapter())
    domain = Relation([()], schema=())
    quantity = Quantity("flow", "item", "period")
    a = Port("a", Indexed(domain, {(): 0}, context), quantity)
    b = Port("b", Indexed(domain, {(): rhs}, context), quantity)
    assembly = Assembly(context, name="links")
    assembly.register(a, required=True)
    assembly.register(b, required=True)
    assembly.add(plan_equal(a, b, name="constant"))
    report = assembly.apply()
    assert report.constant_false_count == rhs
    assert supply_chain.solve(model) == expected
