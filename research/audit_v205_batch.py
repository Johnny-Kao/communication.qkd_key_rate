"""Focused, read-only QKD correctness probes against TNO v2.0.5.

Each probe checks an independently observable condition; a detected anomaly is not
by itself a security-vulnerability finding. No upstream writes or real QKD data.
This script runs once in an isolated GitHub Actions Ubuntu runner.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import textwrap
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.stats import poisson

from tno.quantum.communication.qkd_key_rate.classical import Message, Permutations, Schedule
from tno.quantum.communication.qkd_key_rate.classical._parity_strategy import ParityStrategy
from tno.quantum.communication.qkd_key_rate.classical._corrector import Corrector
from tno.quantum.communication.qkd_key_rate.classical.privacy_amplification import PrivacyAmplification
from tno.quantum.communication.qkd_key_rate.classical.winnow import WinnowSender, WinnowReceiver, WinnowCorrector
from tno.quantum.communication.qkd_key_rate.quantum import Detector, standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bb84, bbm92
from tno.quantum.communication.qkd_key_rate.quantum.bb84 import BB84FiniteKeyRateEstimate, BB84FullyAsymptoticKeyRateEstimate

RUNS = []
P = []

def register(cid, title, classification):
    def decorate(fn):
        P.append((cid, title, classification, fn))
        return fn
    return decorate

def value(x):
    return float(np.asarray(x).item())

def make_detector(*, error_detector=0):
    return standard_detector.customise(
        dark_count_rate=1e-8, polarization_drift=0,
        error_detector=error_detector, efficiency_party=1,
    )

def finite_bb84_case():
    return dict(
        mu=[0.980057214, 0.0576948581, 0.0000029565],
        attenuation=0,
        probability_basis_X=[0.849999575, 0.099999950, 0.049999975],
        probability_basis_Z=[4.25e-7, 5e-8, 2.5e-8],
    )

@register("Q01", "BB84 finite entropy bound beyond one half", "math-invariant")
def bb84_entropy_cap():
    inputs = []
    original = bb84.h
    def track(x):
        inputs.append(value(x))
        return original(x)
    with patch.object(bb84, "h", track):
        est = BB84FiniteKeyRateEstimate(detector=standard_detector, number_of_pulses=int(1e9), number_of_decoy=2)
        rate = value(est.compute_rate(**finite_bb84_case()))
    return {"observed": inputs[1] > .5, "entropy_inputs": inputs, "key_rate": rate, "expected_phase_entropy_bound": .5}

@register("Q02", "BB84 finite secrecy-budget sign", "proof-contract")
def security_budget():
    tree = ast.parse(textwrap.dedent(inspect.getsource(BB84FiniteKeyRateEstimate.compute_rate)))
    values = {}
    for x in tree.body[0].body:
        if isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name):
            try:
                values[x.targets[0].id] = ast.literal_eval(x.value)
            except (ValueError, TypeError, SyntaxError):
                continue
    sec, eps, e1, e2, e3 = (values[k] for k in ["epsilon_security", "epsilon", "epsilon_1", "epsilon_2", "epsilon_3"])
    budget = sec - eps
    minimum_eps = 2*e1+e2+e3
    return {"observed": budget < 0, "epsilon_security": sec, "epsilon": eps, "epsilon_security_minus_epsilon": budget,
            "epsilon_2e1_plus_e2_plus_e3": minimum_eps, "paper_requires_positive_remainder": True,
            "squaring_masks_sign": (e2*e3*budget)**2 > 0}

@register("Q03", "BB84 finite LP Chernoff upper-bound multiplication", "math-invariant")
def lp_chernoff_scaling():
    n = 1_000_000
    mu = np.array([.7, .2, .02])
    priors = np.array([.6, .3, .1])
    max_m = 6
    observed = np.array([220000., 70000., 10000.])
    eps_m = np.repeat(1e-8, max_m+1)
    captured = []
    real_linprog = bb84.scipy.optimize.linprog

    def observe_lp(*args, **kwargs):
        captured.append(np.asarray(kwargs["b_ub"]).copy())
        return real_linprog(*args, **kwargs)
    with patch.object(bb84.scipy.optimize, "linprog", side_effect=observe_lp):
        try:
            bb84.solve_finite_lp(
                target_vacuum=0, target_single=1, probabilities_intensity_j=priors,
                mu=mu, max_num_photons=max_m, number_of_pulses=n,
                observed_count=observed, epsilon_mu_j=np.repeat(1e-8, len(mu)),
                epsilon_num_photons_M=eps_m,
                epsilon_num_photons_M_in_basis_B=np.repeat(1e-8, len(mu)),
            )
        except bb84.OptimizationError:
            pass
    assert captured, "linprog did not run"
    number_int = len(mu)
    target_m = max_m
    actual = float(captured[0][2*number_int + (max_m+1) + target_m] * n)
    p_m = float(priors @ poisson.pmf(target_m, mu))
    f = value(bb84.bound_f(n, p_m, eps_m[target_m]))
    desired = min(p_m*n + f, float(observed.sum()))
    used_formula = min(p_m*n + f*n, float(observed.sum()))
    return {"observed": actual > desired + 1, "m": target_m, "N": n,
            "probability_p_m": p_m, "chernoff_f_in_event_counts": f,
            "actual_LP_upper_count": actual, "paper_Eq31_expected_upper_count": desired,
            "source_formula_upper_count": used_formula, "difference": actual-desired,
            "impact_note": "looser constraint, not proof of unsafe overestimation"}

@register("Q04", "BB84 finite Poisson truncated tail off by one", "math-invariant")
def poisson_tail():
    M = 5
    mu = .8
    impl = float(poisson.sf(M+1, mu))
    correct = float(poisson.sf(M, mu))
    term = float(poisson.pmf(M+1, mu))
    return {"observed": correct > impl and math.isclose(correct-impl, term, rel_tol=1e-10),
            "M": M, "mu": mu, "implemented_P_X_ge_M_plus_2": impl,
            "intended_P_X_ge_M_plus_1": correct, "omitted_probability_mass": term,
            "scope": "direct helper with manual truncation M=5; auto-selected M may make impact tiny"}

@register("Q05", "BB84 finite missing basis rejects zero Z", "input-boundary")
def bb84_zero_z():
    args=finite_bb84_case()
    args["probability_basis_X"]=[.7, .2, .1]
    args["probability_basis_Z"]=[0.,0.,0.]
    est=BB84FiniteKeyRateEstimate(detector=standard_detector,number_of_pulses=int(1e9),number_of_decoy=2)
    try:
        rate=est.compute_rate(**args)
        return {"observed": bool(np.asarray(rate).size) and np.isfinite(rate).all(),
                "returned": np.asarray(rate).tolist(), "note":"zero Z must not generate validated finite key"}
    except Exception as e:
        return {"observed": True, "exception":type(e).__name__, "message":str(e)[:130],
                "note":"input-boundary crash; not necessarily security-relevant"}

@register("B01", "BBM92 no Z sample but positive finite rate", "security-contract")
def bbm92_no_z():
    d=make_detector()
    est=bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=int(5e10))
    rate=est.compute_rate(mu=.5,attenuation=.2,probability_basis_X=1.,probability_basis_Z=0.)
    return {"observed": rate > 0, "pZ":0,"pX":1,"key_rate":value(rate),
            "caveat":"BBM92 implementation uses model-derived error rate, not observed basis data"}

@register("B02", "BBM92 phase error entropy beyond one half", "math-invariant")
def bbm92_entropy_cap():
    d=make_detector()
    original=bbm92.one_minus_h
    def rate_for_n(n):
        est=bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=n)
        return value(est.compute_rate(mu=.5,attenuation=.2,probability_basis_X=.5,probability_basis_Z=.5))
    original_25=rate_for_n(25)
    original_50=rate_for_n(50)
    with patch.object(bbm92, "one_minus_h", lambda e: original(np.minimum(e,.5))):
        capped_25=rate_for_n(25)
        capped_50=rate_for_n(50)
    gain,err=bbm92.compute_gain_and_error_rate(d,d,.1,.1,.25)
    phase_upper=err+bbm92.delta(gain*25,err,1e-12)
    return {"observed": original_25>0 and capped_25<0, "N":25,
            "phase_error_upper":value(phase_upper), "old_rate":original_25, "capped_rate":capped_25,
            "N50_old":original_50, "N50_capped":capped_50,
            "caveat":"N=25 original result corresponds to <1 total expected bit; avoid claiming usable secure key"}

@register("B03", "BBM92 n_X pulses versus detected events", "API-units")
def bbm92_nx_units():
    d=make_detector()
    n=int(5e10)
    def compute(nx):
        est=bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=n)
        return value(est.compute_rate(mu=.5,attenuation=.2,probability_basis_X=.5,probability_basis_Z=.5,n_X=nx))
    implicit=compute(None)
    explicit=compute(n//2)
    gain,_=bbm92.compute_gain_and_error_rate(d,d,.1,.1,.25)
    return {"observed": explicit>implicit*2, "N":n, "gain":value(gain),
            "implicit_rate":implicit, "explicit_nx_sent_pulses":n//2,
            "explicit_rate":explicit, "ratio":explicit/implicit}

@register("D01", "Detector consistency check accepts stale derived efficiency", "silent-result")
def detector_efficiency():
    kw=dict(name="synthetic",jitter_source=0.,jitter_detector=0.,
            dead_time=1e-7,detection_window=1.,dark_count_rate=1e-8,interval=1e-7)
    d0=Detector(**kw,efficiency_system=.5,efficiency_detector=.2)
    stale=d0.customise(efficiency_system=.8)
    fresh=Detector(**kw,efficiency_system=.8,efficiency_detector=.2)
    def rate(d):
        return value(BB84FullyAsymptoticKeyRateEstimate(detector=d).compute_rate(mu=.5,attenuation=.2))
    old,correct=rate(stale),rate(fresh)
    return {"observed": stale.efficiency_party != stale.efficiency_system*stale.efficiency_detector and old!=correct,
            "customized_party":stale.efficiency_party,"consistent_party":fresh.efficiency_party,
            "bb84_customized_rate":old,"bb84_reconstructed_rate":correct,"relative_difference":(old-correct)/correct}

@register("D02", "Detector consistency check accepts mismatched dark count", "API-invariant")
def detector_dark():
    kw=dict(name="synthetic",jitter_source=0.,jitter_detector=0.,dead_time=1e-7,
            detection_window=1.,efficiency_system=1.,efficiency_detector=.2,interval=.0001)
    d=Detector(**kw,dark_count_rate=.00001,dark_count_frequency=10.)
    return {"observed": abs(d.dark_count_rate-d.dark_count_frequency*d.interval)>1e-5,
            "rate":d.dark_count_rate,"frequency":d.dark_count_frequency,"interval":d.interval,
            "physically_corresponding_rate":d.dark_count_frequency*d.interval}

class TraceBits:
    def __init__(self,n):
        self.original=list(range(n))
        self.live=list(range(n))
        self.removed=[]
    @property
    def length(self): return len(self.live)
    def pop(self,i):
        original=self.live.pop(i)
        self.removed.append(original)
        return original

def discard_trace(blocks, size=8, n=64):
    s=object.__new__(WinnowSender)
    s._message=TraceBits(n)
    s.number_of_blocks=n//size
    s.number_of_bad_blocks=len(blocks)
    s.bad_blocks_array=list(blocks)+[0]*(s.number_of_blocks-len(blocks))
    s.block_size=size
    s.schedule=Schedule([1])
    s.transcript=""
    s._net_exposed_bits=0
    s.discard_syndrome_bits()
    return s.message.removed

@register("W01", "Winnow discarded bits ignore flagged block offset", "reconciliation-confidentiality")
def winnow_wrong_delete():
    observed=discard_trace([3])
    expected=[3*8+j for j in [0,1,3,7]]
    multiple=discard_trace([1,3])
    return {"observed": observed!=expected, "flagged_block":3,
            "actual_removed_original_positions":observed,"expected":[int(v) for v in expected],
            "two_bad_blocks_removed":multiple, "caveat":"requires security impact proof for the disclosed syndrome"}

@register("W02", "Winnow incorrect deletion survives Alice/Bob equality test", "regression-blind-spot")
def winnow_equal_outputs():
    source=Message.random_message(512,random_state=43)
    receiver=Message(source.message.copy())
    receiver.message[300]^=1
    perms=Permutations([list(range(512)),list(range(512))])
    alice=WinnowSender(source,perms,Schedule([1]))
    bob=WinnowReceiver(receiver,perms,Schedule([1]))
    out=WinnowCorrector(alice,bob).correct_errors()
    return {"observed": out.output_error==0 and out.output_alice==out.output_bob,
            "output_error":out.output_error,"output_length":out.output_length,
            "output_digest_prefix":hashlib.sha256(bytes(out.output_alice)).hexdigest()[:16],
            "note":"demonstrates existing equality checks cannot detect wrong deletion"}

@register("W03", "Winnow syndrome block index boundary", "low-value-boundary")
def winnow_oob_syndrome():
    source=Message.random_message(64,random_state=43)
    perms=Permutations([list(range(64))])
    s=WinnowSender(source,perms,Schedule([1]))
    try:
        x=s.get_syndrome(s.number_of_blocks)
        return {"observed":True, "returned":x,
                "note":"guard uses > instead of >=, but this index may be caller-unreachable"}
    except Exception as e:
        return {"observed":True,"exception":type(e).__name__,
                "note":"public helper accepts out-of-range index; caller reachable status unproven"}

@register("C01", "Cascade end-of-table parity-strategy threshold", "low-value-boundary")
def cascade_threshold():
    try:
        x=ParityStrategy(error_rate=.15).get_start_block_size()
        return {"observed":False,"result":x}
    except ValueError as e:
        return {"observed":True,"exception":str(e),
                "note":"0.15 exists in ERROR_RATES_TO_BLOCK_SIZES but exclusive > comparison rejects exactly 0.15"}

@register("C02", "Cascade prior-error range denominator", "debug-only")
def cascade_range_denominator():
    # Static contract mismatch: subrange loop uses full message length.
    from tno.quantum.communication.qkd_key_rate.classical import cascade
    source=inspect.getsource(cascade.CascadeReceiver.get_prior_error_rate)
    return {"observed":"return number_of_differences / self.message.length" in source,
            "source": "CascadeReceiver.get_prior_error_rate",
            "note":"subrange denominator uses full message length; function documents debugging only"}

@register("P01", "PrivacyAmplification deterministic SHAKE and unbounded requested entropy", "security-design")
def hash_entropy():
    privacy=PrivacyAmplification(1,0)
    msg=Message([1])
    h1=privacy.do_hash(msg,128)
    h2=privacy.do_hash(msg,128)
    ent=privacy.get_entropy_estimate()
    return {"observed": len(h1)==128 and h1==h2 and ent==1.,
            "input_bits":1,"estimated_entropy_bits":ent,"requested_hash_output_bits":len(h1),
            "deterministic":h1==h2,
            "caveat":"caller-supplied entropy may be intentionally trusted; no universal-hash guarantee established"}

@register("M01", "Message bit mutation bypasses binary validation", "low-value-input")
def message_bit_setter():
    m=Message([0,1,0])
    m[1]=7
    return {"observed":m.message[1]==7,"value":m.message,
            "note":"setter bypasses constructor validation; requires normal-path reachability"}

def main():
    print("TNO QKD OFFICIAL v2.0.5 GLOBAL AUDIT | synthetic inputs | no upstream mutation",flush=True)
    failures=0
    for cid,title,kind,fn in P:
        try:
            evidence=fn()
            observed=evidence.get("observed")
            status="REPRODUCED_SIGNAL" if observed else "NOT_REPRODUCED"
            if observed is None:
                status="INCONCLUSIVE"
            item={"id":cid,"title":title,"class":kind,"status":status,"evidence":evidence}
        except Exception as exc:
            failures+=1
            item={"id":cid,"title":title,"class":kind,"status":"HARNESS_ERROR",
                  "error":repr(exc),"traceback":traceback.format_exc(limit=3)}
        RUNS.append(item)
        print(json.dumps(item,ensure_ascii=False,default=str),flush=True)
    summary={"total":len(RUNS),
             "reproduced_signals":sum(x["status"]=="REPRODUCED_SIGNAL" for x in RUNS),
             "not_reproduced":sum(x["status"]=="NOT_REPRODUCED" for x in RUNS),
             "harness_errors":failures,
             "disclaimer":"A reproduced signal is NOT automatically a confirmed security vulnerability."}
    Path("audit_v205_results.json").write_text(json.dumps({"summary":summary,"results":RUNS},indent=2,default=str)+"\n")
    print("AUDIT SUMMARY:",json.dumps(summary),flush=True)
    raise SystemExit(2 if failures else 0)

if __name__=="__main__":
    main()
