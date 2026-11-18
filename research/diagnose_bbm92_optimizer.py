"""GC-only reproduction and alternative-solver study for official v2.0.5 BBM92.

No production source changes; all inputs come from test_required_linktime.py.
"""
from __future__ import annotations

import json
import math
import platform
import time
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
import scipy
from scipy import optimize

from tno.quantum.communication.qkd_key_rate.quantum import standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bbm92


BASELINE_PULSES = [
    int(factor * 10**exp)
    for exp in (9, 10, 11)
    for factor in range(1, 10)
]
ATTENUATIONS = [5, 10, 15, 20]
REPORT: dict = {
    "python": platform.python_version(),
    "scipy": scipy.__version__,
    "numpy": np.__version__,
    "baseline_sha": "7266c35e38ebc52bf9542649963a8a0a613cb8c6",
    "baseline": [],
    "alternatives": [],
}


def number(v):
    try:
        return float(np.asarray(v).ravel()[0])
    except (ValueError, TypeError, IndexError):
        return str(v)


def fresh_estimator(pulses):
    return bbm92.BBM92FiniteKeyRateEstimate(
        detector=standard_detector, number_of_pulses=pulses
    )


def baseline(pulses, attenuation):
    calls = []
    original_minimize = optimize.minimize

    def record_minimize(*args, **kwargs):
        result = original_minimize(*args, **kwargs)
        calls.append(
            {
                "success": bool(result.success),
                "status": int(result.status),
                "message": str(result.message)[:200],
                "fun": number(result.fun),
                "x": np.asarray(result.x).tolist(),
                "nit": int(result.get("nit", -1)),
                "nfev": int(result.get("nfev", -1)),
                "constr_violation": number(result.get("constr_violation", 0.0)),
            }
        )
        return result

    start = time.monotonic()
    try:
        with patch.object(bbm92.scipy.optimize, "minimize", side_effect=record_minimize):
            parameters, rate = fresh_estimator(pulses).optimize_rate(
                attenuation=attenuation
            )
        result = {"status": "success", "rate": number(rate), "parameters": {
            k: np.asarray(v).tolist() for k, v in parameters.items()
        }}
    except Exception as exc:
        result = {"status": "failure", "exception": type(exc).__name__,
                  "message": str(exc)[:200]}
    result.update({"N": pulses, "attenuation": attenuation,
                   "duration_s": round(time.monotonic()-start, 3),
                   "minimizer_attempts": calls})
    return result


def alternatives(pulses, attenuation):
    # A truly independent positive-rate witness: direct compute_rate from an
    # analytically feasible selection (mu, P_X, P_Z) without optimizing.
    grid = []
    for mu in (0.02, 0.06, 0.15, 0.3, 0.5, 0.75):
        for px in (0.2, 0.5, 0.8, 0.95):
            estimator = fresh_estimator(pulses)
            try:
                rate = number(estimator.compute_rate(
                    mu=np.array([mu]), attenuation=attenuation,
                    probability_basis_X=np.array([px]),
                    probability_basis_Z=np.array([1-px]),
                ))
                if math.isfinite(rate):
                    grid.append((rate, mu, px))
            except Exception:
                pass
    grid.sort(reverse=True)
    result = {
        "N": pulses, "attenuation": attenuation,
        "grid_evaluated": len(grid),
        "top_grid": [
            {"rate": a, "mu": b, "px": c}
            for a, b, c in grid[:3]
        ],
    }
    # Compare candidate local optimizers with same constrained objective.
    for method in ("SLSQP", "trust-constr"):
        result[method] = []
        for x0 in ([0.405, 0.5, 0.5], [0.1, 0.7, 0.3]):
            estimator = fresh_estimator(pulses)
            estimator.last_positive_key_rate = -1.0
            estimator.last_x = np.array(x0, dtype=float)
            try:
                original_bounds = optimize.Bounds(
                    [.01, 0, 0], [.8, 1, 1]
                )
                c = optimize.LinearConstraint([0, 1, 1], [1], [1])
                opts = (
                    {"maxiter": 500, "ftol": 1e-11}
                    if method == "SLSQP"
                    else {"maxiter": 500, "finite_diff_rel_step": 1e-6}
                )
                solve = optimize.minimize(
                    estimator._f, np.array(x0, dtype=float),
                    args=({"attenuation": attenuation},),
                    method=method, jac="2-point",
                    constraints=c, bounds=original_bounds,
                    options=opts,
                )
                x = np.asarray(solve.x, dtype=float)
                # Independently reevaluate at the returned parameters;
                # checking res.success alone is insufficient.
                rate = number(fresh_estimator(pulses).compute_rate(
                    mu=np.array([x[0]]), attenuation=attenuation,
                    probability_basis_X=np.array([x[1]]),
                    probability_basis_Z=np.array([x[2]]),
                ))
                result[method].append({
                    "x0": x0, "solver_success": bool(solve.success),
                    "status": int(solve.status),
                    "message": str(solve.message)[:120],
                    "x": x.tolist(), "objective_rate": -number(solve.fun),
                    "independent_rate": rate,
                    "constraint_residual": abs(float(x[1] + x[2] - 1.0)),
                    "nit": int(solve.get("nit", -1)),
                })
            except Exception as exc:
                result[method].append({
                    "x0": x0, "exception": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                })
    return result


def main():
    failures = []
    for attenuation in ATTENUATIONS:
        # Mirror the official loop: creating a fresh estimator per N.
        observed_failure = False
        for pulses in BASELINE_PULSES:
            entry = baseline(pulses, attenuation)
            REPORT["baseline"].append(entry)
            print("BASELINE", json.dumps(entry), flush=True)
            if entry["status"] == "failure":
                failures.append(entry)
                observed_failure = True
                break
        if not observed_failure:
            print("BASELINE COMPLETE", attenuation, flush=True)
    selected = [
        (1_000_000_000, 5),
        (1_000_000_000, 10),
        (1_000_000_000, 15),
    ]
    selected.extend((r["N"], r["attenuation"]) for r in failures)
    seen = set()
    for pulses, attenuation in selected:
        if (pulses, attenuation) in seen:
            continue
        seen.add((pulses, attenuation))
        out = alternatives(pulses, attenuation)
        REPORT["alternatives"].append(out)
        print("ALTERNATIVES", json.dumps(out), flush=True)
    REPORT["summary"] = {
        "baseline_trials": len(REPORT["baseline"]),
        "baseline_failures": len(failures),
        "failure_cases": [
            {"N": e["N"], "attenuation": e["attenuation"],
             "exception": e["exception"]}
            for e in failures
        ],
        "diagnostic_only": True,
    }
    Path("bbm92_optimizer_diagnostics.json").write_text(
        json.dumps(REPORT, indent=2, allow_nan=False) + "\n"
    )
    print("SUMMARY", json.dumps(REPORT["summary"]), flush=True)


if __name__ == "__main__":
    main()
