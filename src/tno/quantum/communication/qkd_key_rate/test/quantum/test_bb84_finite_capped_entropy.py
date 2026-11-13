"""Regression tests for capped phase-error entropy in finite BB84."""

import numpy as np
import pytest

from tno.quantum.communication.qkd_key_rate.quantum import standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bb84


@pytest.mark.parametrize("force_large_lp_bound", [False, True])
def test_finite_phase_error_entropy_is_capped(monkeypatch, force_large_lp_bound: bool) -> None:
    """Both finite-key privacy terms must saturate at phase-error bound 1/2."""
    entropy_inputs: list[float] = []
    original_h = bb84.h
    original_delta = bb84.delta

    def record_h(value):
        entropy_inputs.append(float(np.asarray(value).item()))
        return original_h(value)

    def phase_delta(n_x, n_z, epsilon):
        if force_large_lp_bound and epsilon == 1e-7:
            return 0.6
        return original_delta(n_x, n_z, epsilon)

    monkeypatch.setattr(bb84, "h", record_h)
    if force_large_lp_bound:
        monkeypatch.setattr(bb84, "delta", phase_delta)

    estimator = bb84.BB84FiniteKeyRateEstimate(
        detector=standard_detector,
        number_of_pulses=int(1e9),
        number_of_decoy=2,
    )
    estimator.compute_rate(
        mu=[0.980057214, 0.0576948581, 0.0000029565],
        attenuation=0,
        probability_basis_X=[0.849999575, 0.099999950, 0.049999975],
        probability_basis_Z=[4.25e-7, 5e-8, 2.5e-8],
    )

    assert len(entropy_inputs) == 3
    if force_large_lp_bound:
        assert entropy_inputs[0] == pytest.approx(0.5)
    else:
        assert entropy_inputs[1] == pytest.approx(0.5)
