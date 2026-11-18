"""Pre-upstream evidence for finite BB84's unresolved security budget.

These tests deliberately do not replace the paper's failure probabilities with
arbitrary numbers. The reference theorem and LP failure allocation must agree.
"""

import ast
import inspect
import math
import textwrap

import pytest

from tno.quantum.communication.qkd_key_rate.quantum.bb84 import (
    BB84FiniteKeyRateEstimate,
)


def _source_security_defaults() -> dict[str, float]:
    parsed = ast.parse(textwrap.dedent(inspect.getsource(
        BB84FiniteKeyRateEstimate.compute_rate
    )))
    constants = {}
    for statement in parsed.body[0].body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            try:
                constants[statement.targets[0].id] = ast.literal_eval(
                    statement.value
                )
            except (ValueError, TypeError):
                pass
    keys = (
        "epsilon_security",
        "epsilon",
        "epsilon_1",
        "epsilon_2",
        "epsilon_3",
    )
    return {key: constants[key] for key in keys}


def test_reproduce_existing_negative_secrecy_budget() -> None:
    values = _source_security_defaults()
    assert values["epsilon_security"] == 2e-50
    assert values["epsilon"] == 1e-7
    assert values["epsilon_security"] - values["epsilon"] < 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Official v2.0.5 constants violate Eq. (22): "
        "epsilon=2*epsilon_1+epsilon_2+epsilon_3 "
        "and epsilon_security>epsilon. Full budget including LP errors "
        "requires independent proof before any numerical fix."
    ),
)
def test_security_budget_meets_cited_theorem() -> None:
    values = _source_security_defaults()
    expected = (
        2 * values["epsilon_1"]
        + values["epsilon_2"]
        + values["epsilon_3"]
    )
    assert math.isclose(values["epsilon"], expected, rel_tol=1e-12)
    assert 0 < values["epsilon"] < values["epsilon_security"]
