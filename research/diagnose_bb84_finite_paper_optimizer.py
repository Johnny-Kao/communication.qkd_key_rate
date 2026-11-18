"""GC-only differential diagnosis: corrected paper LP vs BB84 optimizer.

No assertions about global optimality. Demonstrates feasible positive
physical rates independently of the optimizer whenever they exist.
"""
import json
import platform
import time
from unittest.mock import patch

import numpy as np
from scipy.optimize import OptimizeResult

from tno.quantum.communication.qkd_key_rate.quantum import standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bb84

N = int(1e9)
LOSS = [1., 2., 3., 4.]
PARAMS = [
    ([.7, .12], [.78, .12], [.08, .02]),
    ([.5, .05], [.8, .1], [.08, .02]),
    ([.9, .18], [.8, .1], [.08, .02]),
    ([.7, .12], [.55, .25], [.15, .05]),
    ([.55, .05], [.5, .40], [.08, .02]),
    ([.2, .01], [.6, .2], [.1, .1]),
]

def rate_with(params, attenuation):
    estimator = bb84.BB84FiniteKeyRateEstimate(
        detector=standard_detector, number_of_pulses=N, number_of_decoy=1
    )
    m, px, pz = params
    try:
        val = estimator.compute_rate(
            mu=np.asarray(m), attenuation=attenuation,
            probability_basis_X=np.asarray(px),
            probability_basis_Z=np.asarray(pz),
        )
        return {"rate": float(np.asarray(val).ravel()[0]), "valid": True}
    except Exception as exc:
        return {"exception": str(exc)[:180], "type": type(exc).__name__, "valid": False}


def original_optimizer(attenuation):
    attempts = []
    original = bb84.scipy.optimize.minimize

    def record(*args, **kwargs):
        try:
            res = original(*args, **kwargs)
        except Exception as exc:
            attempts.append({"exception": repr(exc)})
            raise
        attempts.append({
            "x": np.asarray(res.x).tolist(),
            "fun": float(np.asarray(res.fun).ravel()[0]),
            "success": bool(res.success),
            "status": int(res.status),
            "message": str(res.message)[:120],
            "nit": int(res.get("nit", -1)),
        })
        return res

    inst = bb84.BB84FiniteKeyRateEstimate(
        detector=standard_detector, number_of_pulses=N, number_of_decoy=1
    )
    with patch.object(bb84.scipy.optimize, "minimize", side_effect=record):
        try:
            params, rate = inst.optimize_rate(attenuation=attenuation)
            return {"rate": float(rate), "parameters":{
                k:np.asarray(v).tolist() for k,v in params.items()
            }, "attempts":attempts}
        except Exception as exc:
            return {"exception":repr(exc), "attempts":attempts}


def main():
    print("ENV",json.dumps({
        "python":platform.python_version(), "numpy":np.__version__,
        "scipy":bb84.scipy.__version__
    }),flush=True)
    for att in LOSS:
        candidates = []
        for params in PARAMS:
            res = rate_with(params, att)
            candidates.append({"mu":params[0],"px":params[1],"pz":params[2],**res})
        # Small independent source parameter grid, not a solver.
        for strong in [.35,.55,.75,.9]:
            for weak in [.015,.06,.12]:
                for pz in [.03,.08,.15]:
                    if weak>=strong: continue
                    px=[1-pz-.04,.04]
                    zz=[pz*.8,pz*.2]
                    params=([strong,weak],px,zz)
                    res=rate_with(params,att)
                    candidates.append({"mu":params[0],"px":params[1],"pz":params[2],**res})
        positives=sorted([v for v in candidates if v.get("rate",-1)>0],
                         key=lambda v:v["rate"],reverse=True)
        results={
            "attenuation":att,
            "tested":len(candidates),
            "positive":len(positives),
            "best_positive":positives[:3],
            "nonfinite":len([v for v in candidates if not v["valid"]]),
            "optimizer":original_optimizer(att)
        }
        print("DIAG",json.dumps(results),flush=True)


if __name__=="__main__":
    main()
