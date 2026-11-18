"""GC regression for BBM92's false 'no positive solution' optimizer failures."""

from unittest.mock import patch

import numpy as np
import pytest
from scipy import optimize

from tno.quantum.communication.qkd_key_rate.quantum import standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bbm92
from tno.quantum.communication.qkd_key_rate.quantum._config import (
    OptimizationError,
)


@pytest.mark.parametrize(
    ("number_of_pulses", "attenuation"),
    [
        (int(8e11), 5),
        (int(2e11), 10),
        (int(2e11), 15),
        (int(1e9), 20),
    ],
)
def test_known_original_failures_have_a_feasible_positive_rate(
    number_of_pulses: int, attenuation: int
) -> None:
    model = bbm92.BBM92FiniteKeyRateEstimate(
        detector=standard_detector, number_of_pulses=number_of_pulses
    )
    params, rate = model.optimize_rate(attenuation=attenuation)
    assert np.isfinite(rate) and rate > 0
    np.testing.assert_allclose(
        params["probability_basis_X"] + params["probability_basis_Z"],
        [1.0],
        atol=1e-7,
        rtol=0,
    )
    # Rate must be from valid production compute_rate, not a synthetic fallback
    # or an optimizer's unverified success flag.
    independent = bbm92.BBM92FiniteKeyRateEstimate(
        detector=standard_detector, number_of_pulses=number_of_pulses
    ).compute_rate(attenuation=attenuation, **params)
    assert rate == pytest.approx(float(independent), abs=1e-12, rel=1e-7)


def test_negative_trust_results_trigger_real_positive_slsqp_recovery() -> None:
    original_minimize = optimize.minimize
    methods = []

    def deliberately_stuck(*args, **kwargs):
        method = kwargs.get("method")
        methods.append(method)
        if method == "trust-constr":
            return optimize.OptimizeResult(
                success=True, status=2, fun=0.0001,
                x=np.array([0.405, 0.5, 0.5]),
            )
        return original_minimize(*args, **kwargs)

    with patch.object(bbm92.scipy.optimize, "minimize", side_effect=deliberately_stuck):
        result = bbm92.BBM92FiniteKeyRateEstimate(
            detector=standard_detector, number_of_pulses=int(8e11)
        ).optimize_rate(attenuation=5)

    params, rate = result
    assert methods == ["trust-constr"] * 3 + ["SLSQP"]
    assert rate > 0
    assert 0.01 <= float(params["mu"][0]) <= 0.8


def test_invalid_fallback_cannot_fake_a_feasible_key() -> None:
    original_minimize = optimize.minimize

    def always_invalid(*args, **kwargs):
        if kwargs.get("method") == "trust-constr":
            return optimize.OptimizeResult(
                success=True, status=2, fun=0.001,
                x=np.array([0.405, 0.5, 0.5]),
            )
        return optimize.OptimizeResult(
            success=True, status=0, fun=-0.6,
            x=np.array([0.4, 0.9, 0.9]),
        )

    with patch.object(bbm92.scipy.optimize, "minimize", side_effect=always_invalid):
        with pytest.raises(OptimizationError, match="Unable to find solution"):
            bbm92.BBM92FiniteKeyRateEstimate(
                detector=standard_detector, number_of_pulses=int(8e11)
            ).optimize_rate(attenuation=5)


def test_existing_positive_trust_result_does_not_require_slsqp() -> None:
    used = []

    def immediate_success(*args, **kwargs):
        used.append(kwargs.get("method"))
        return optimize.OptimizeResult(
            success=True, status=1, fun=-0.0001,
            x=np.array([0.15, 0.5, 0.5]),
        )

    with patch.object(bbm92.scipy.optimize, "minimize", side_effect=immediate_success):
        _, rate = bbm92.BBM92FiniteKeyRateEstimate(
            detector=standard_detector, number_of_pulses=int(1e9)
        ).optimize_rate(attenuation=5)

    assert rate == pytest.approx(0.0001)
    assert used == ["trust-constr"]
