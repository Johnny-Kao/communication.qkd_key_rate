"""Research-only finite BB84 search from alternative feasible seeds (GC)."""
import json
import numpy as np
from scipy.optimize import minimize, Bounds
from tno.quantum.communication.qkd_key_rate.quantum import bb84, standard_detector

SEEDS=[
[.2,.01,.6,.2,.1,.1],
[.2,.01,.75,.1,.075,.075],
[.15,.015,.65,.2,.1,.05],
[.3,.005,.55,.25,.15,.05],
[.25,.03,.6,.25,.1,.05],
[.35,.03,.8,.08,.08,.04],
[.6,.05,.8,.08,.08,.04],
]
def fresh():
    return bb84.BB84FiniteKeyRateEstimate(detector=standard_detector,number_of_pulses=int(1e9),number_of_decoy=1)
def independent(x,att):
    e=fresh()
    try:
        return float(np.asarray(e.compute_rate(mu=x[:2],attenuation=att,probability_basis_X=x[2:4],probability_basis_Z=x[4:])).item())
    except Exception:
        return float("nan")
def rows():
    for att in [1.,2.,3.,4.]:
        data=[]
        for seed in SEEDS:
            row={"seed":seed,"seed_rate":independent(np.array(seed),att)}
            e=fresh()
            try:
                p,r=e.optimize_rate(attenuation=att,x0=np.array(seed,dtype=float))
                row["trust"]={"rate":float(r),"param":{k:v.tolist() for k,v in p.items()}}
            except Exception as exc:
                row["trust"]={"error":str(exc)}
            e=fresh();e.last_positive_key_rate=-1.;e.last_x=np.array(seed)
            try:
                # Original nonnegativity and basis-total constraints. SLSQP
                # compares a solver class; no change to package code.
                a={"attenuation":att}
                cons=[
                    {"type":"eq","fun":lambda x:sum(x[2:])-1.0},
                    {"type":"ineq","fun":lambda x:float(x[0]-x[1])},
                ]
                res=minimize(e._f,np.array(seed,dtype=float),args=(a,),
                    method="SLSQP",
                    bounds=Bounds([1e-16,1e-16,0,0,0,0],[1,1,1,1,1,1]),
                    constraints=cons,
                    options={"ftol":1e-12,"maxiter":300}
                )
                row["slsqp"]={"success":bool(res.success),"message":str(res.message),
                    "rate":-float(res.fun),"independent_rate":independent(res.x,att),
                    "x":res.x.tolist(),"nit":int(res.nit)}
            except Exception as exc:
                row["slsqp"]={"error":str(exc)}
            data.append(row)
        out={"attenuation":att,"cases":data}
        print("ALTERNATIVE",json.dumps(out),flush=True)
if __name__=="__main__":
    rows()
