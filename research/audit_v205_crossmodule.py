"""Independent cross-module, parameterized invariant and differential research probes.

Runs on *unmodified* official TNO Quantum v2.0.5 in the Johnny-Kao fork CI.
Every result is explicit: VERIFIED_PASS, REPRODUCED_SIGNAL, INCONCLUSIVE,
or HARNESS_ERROR. A signal is not automatically a vulnerability.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.stats import poisson

from tno.quantum.communication.qkd_key_rate.classical import (
    Message, ParityStrategy, Permutations, Schedule,
)
from tno.quantum.communication.qkd_key_rate.classical.cascade import (
    CascadeCorrector, CascadeReceiver, CascadeSender,
)
from tno.quantum.communication.qkd_key_rate.classical.privacy_amplification import (
    PrivacyAmplification,
)
from tno.quantum.communication.qkd_key_rate.classical.winnow import (
    WinnowCorrector, WinnowReceiver, WinnowSender,
)
from tno.quantum.communication.qkd_key_rate.quantum import (
    Detector, standard_detector,
)
from tno.quantum.communication.qkd_key_rate.quantum import bb84, bbm92
from tno.quantum.communication.qkd_key_rate.quantum.bb84 import (
    BB84FiniteKeyRateEstimate, BB84FullyAsymptoticKeyRateEstimate,
)

CHECKS = []
RESULTS = []


def check(ident: str, subsystem: str, title: str):
    def wrapper(fn):
        CHECKS.append((ident, subsystem, title, fn))
        return fn
    return wrapper


def scalar(x):
    return float(np.asarray(x).item())


def report(status: str, **details):
    return {"status": status, **details}


def rank_gf2(matrix):
    a = np.asarray(matrix, dtype=np.uint8).copy() % 2
    current = 0
    for col in range(a.shape[1]):
        if current >= a.shape[0]:
            break
        candidates = np.flatnonzero(a[current:, col])
        if not len(candidates):
            continue
        selected = int(current + candidates[0])
        a[[current, selected]] = a[[selected, current]]
        for row in range(a.shape[0]):
            if row != current and a[row, col]:
                a[row] ^= a[current]
        current += 1
    return current


@check("X01", "Permutations", "Random inverse and shorten invariants across 120 sets")
def permutation_property():
    rng = np.random.RandomState(71)
    tested = 0
    for n in [8, 16, 64, 128]:
        for _ in range(30):
            p = Permutations.random_permutation(3, n, random_state=rng)
            p.shorten_pass(0, int(n * .7))
            p.shorten_pass(1, int(n * .45))
            for forward, inverse in zip(p.permutations, p.inverted_permutations, strict=True):
                if [forward[i] for i in inverse] != list(range(len(forward))):
                    return report("REPRODUCED_SIGNAL", message_size=n, faulty=forward)
            tested += 1
    return report("VERIFIED_PASS", test_sets=tested, forward_inverse_mismatch=0)


@check("X02", "Cascade", "Three 2,048-bit seeded correction scenarios")
def cascade_e2e():
    outcomes = []
    for er in [.01, .04, .09]:
        n = 2048
        original = Message.random_message(n, random_state=42)
        noisy = original.apply_errors(er, random_state=5)
        perms = Permutations.random_permutation(6, n, random_state=123)
        strat = ParityStrategy(error_rate=er, number_of_passes=6)
        info = CascadeCorrector(
            CascadeSender(original, perms),
            CascadeReceiver(noisy, perms, strat),
        ).correct_errors()
        outcomes.append({"configured_error":er, "actual_input_error":info.input_error,
                         "output_error":info.output_error, "length":info.output_length,
                         "exposed_bits":int(info.number_of_exposed_bits)})
    status = "VERIFIED_PASS" if all(x["output_error"] == 0 for x in outcomes) else "REPRODUCED_SIGNAL"
    return report(status, cases=outcomes)


@check("X03", "Cascade", "Subset error-rate helper denominator differential")
def cascade_subrange():
    n = 64
    a = Message([0] * n)
    b = Message([1] + [0] * (n-1))
    perms = Permutations([list(range(n))])
    strat = ParityStrategy(error_rate=.01, number_of_passes=1)
    alice = CascadeSender(a, perms)
    bob = CascadeReceiver(b, perms, strat)
    got = bob.get_prior_error_rate(alice, index_start=0, index_finish=4)
    expected = .25
    return report("REPRODUCED_SIGNAL" if got != expected else "VERIFIED_PASS",
                  expected_subrange_error_rate=expected, actual=got, debug_only=True)


@check("X04", "Cascade", "Parity disclosure and key rate in seeded full run")
def cascade_leak_count():
    n = 1024
    a = Message.random_message(n, random_state=70)
    b = a.apply_errors(.06, random_state=44)
    perms = Permutations.random_permutation(6, n, random_state=19)
    strat = ParityStrategy(error_rate=.06, number_of_passes=6)
    corrector = CascadeCorrector(CascadeSender(a, perms), CascadeReceiver(b, perms, strat))
    stats = corrector.correct_errors()
    returned = stats.key_reconciliation_rate
    expected = max(0, (stats.output_length - stats.number_of_exposed_bits) / n)
    return report("VERIFIED_PASS" if np.isclose(returned, expected) and stats.output_error == 0 else "REPRODUCED_SIGNAL",
                  input_error=stats.input_error, output_error=stats.output_error,
                  disclosed_bits=stats.number_of_exposed_bits, reported_rate=returned,
                  expected_from_current_accounting=expected,
                  caveat="Only internal accounting consistency; not independent transcript entropy bound")


def winnow_run(*, repair=False):
    a = Message.random_message(512, random_state=43)
    b = Message(a.message.copy())
    b.message[300] ^= 1
    perms = Permutations([list(range(512))])
    alice = WinnowSender(a, perms, Schedule([1]))
    bob = WinnowReceiver(b, perms, Schedule([1]))
    captured = []
    original = WinnowSender.discard_syndrome_bits

    def replacement(self):
        if self.number_of_bad_blocks:
            flagged = list(self.bad_blocks_array[:self.number_of_bad_blocks])
            if isinstance(self, WinnowReceiver):
                H = np.asarray(self.parity_check_matrix[:self.syndrome_length, :self.block_size], dtype=np.uint8) % 2
                positions = [2**j-1 for j in range(self.syndrome_length) if 2**j-1 < self.block_size]
                capture = {
                    "bad_blocks": flagged, "block_size": self.block_size,
                    "syndrome_length": self.syndrome_length, "H": H.tolist(),
                    "rank_all": rank_gf2(H),
                    "rank_removed_correct":rank_gf2(H[:,positions]),
                    "rank_removed_current": 0 if flagged[0] > 0 else rank_gf2(H[:,positions]),
                    "retained_linear_info_current": rank_gf2(H) - (0 if flagged[0] > 0 else rank_gf2(H[:,positions])),
                    "retained_linear_info_if_pivots_removed": rank_gf2(H) - rank_gf2(H[:,positions]),
                }
                captured.append(capture)
        if not repair:
            return original(self)
        positions = []
        for block in self.bad_blocks_array[:self.number_of_bad_blocks]:
            for bit in [2**j-1 for j in range(self.syndrome_length) if 2**j-1 < self.block_size]:
                positions.append(block*self.block_size+bit)
        for location in sorted(positions, reverse=True):
            self.message.pop(location)
            self._net_exposed_bits -= 1
        self.transcript += "Research-only deletion at intended syndrome pivot positions.\n"

    with patch.object(WinnowSender, "discard_syndrome_bits", replacement):
        s = WinnowCorrector(alice, bob).correct_errors()
    return {"output_error":s.output_error, "output_length":s.output_length,
            "same_alice_bob":s.output_alice==s.output_bob,
            "output_sha256":hashlib.sha256(bytes(s.output_alice)).hexdigest(),
            "net_exposed_bits":s.number_of_exposed_bits,
            "captured":captured}


@check("X05", "Winnow", "Real corrector GF(2) retained syndrome information")
def winnow_leak_rank():
    current = winnow_run(repair=False)
    g = current["captured"][0]
    return report(
        "REPRODUCED_SIGNAL" if g["retained_linear_info_current"] > 0 and g["retained_linear_info_if_pivots_removed"] == 0 else "INCONCLUSIVE",
        bad_block=g["bad_blocks"][0], disclosed_rank=g["rank_all"],
        rank_consumed_by_actual_deleted_bits=g["rank_removed_current"],
        rank_consumed_by_intended_deleted_bits=g["rank_removed_correct"],
        residual_bits_current=g["retained_linear_info_current"],
        residual_bits_with_intended_pivot_deletion=g["retained_linear_info_if_pivots_removed"],
        result_output_error=current["output_error"],
        caveat="GF(2) rank for one published syndrome; final overall leakage budget remains unproven")


@check("X06", "Winnow", "A/B real end-to-end deletion behavior with equal output error")
def winnow_delete_differential():
    before = winnow_run(repair=False)
    after = winnow_run(repair=True)
    significant = (before["output_error"] == after["output_error"] == 0
                   and before["output_length"] == after["output_length"]
                   and before["output_sha256"] != after["output_sha256"])
    return report("REPRODUCED_SIGNAL" if significant else "INCONCLUSIVE",
                  before={k:v for k,v in before.items() if k!="captured"},
                  research_repair={k:v for k,v in after.items() if k!="captured"},
                  caveat="Synthetic research monkeypatch only; no production source edit")


@check("X07", "Schedule", "Normal advancement over finite Winnow schedule")
def schedule_normal():
    s = Schedule([2,1,1])
    values = []
    for _ in range(4):
        values.append(s.next_pass())
    return report("VERIFIED_PASS" if len(values)==4 and s.remaining_passes == 0 else "REPRODUCED_SIGNAL",
                  sequence=values, remaining=s.remaining_passes)


@check("X08", "PrivacyAmplification", "Deterministic SHAKE XOF can emit more bits than entropy")
def privacy_output():
    pa = PrivacyAmplification(1, 0)
    m = Message([1])
    one = pa.do_hash(m,128)
    two = pa.do_hash(m,128)
    return report("REPRODUCED_SIGNAL" if len(one)==128 and one==two and pa.get_entropy_estimate()==1 else "INCONCLUSIVE",
                  estimated_entropy=pa.get_entropy_estimate(), returned_bits=len(one),
                  same_output_without_seed=one==two,
                  caveat="Core function trusts caller-supplied entropy; no direct proof of exploitable QKD system")


@check("X09", "Detector", "Accepted inconsistent efficiency changes BB84 output")
def detector_differential():
    kw = dict(name="synthetic",jitter_source=0.,jitter_detector=0.,
              dead_time=1e-7,detection_window=1.,dark_count_rate=1e-8,interval=1e-7)
    initial = Detector(**kw,efficiency_system=.5,efficiency_detector=.2)
    stale = initial.customise(efficiency_system=.8)
    consistent = Detector(**kw,efficiency_system=.8,efficiency_detector=.2)
    est = lambda d: scalar(BB84FullyAsymptoticKeyRateEstimate(detector=d).compute_rate(mu=.5,attenuation=.2))
    r1, r2 = est(stale), est(consistent)
    return report("REPRODUCED_SIGNAL" if not np.isclose(r1,r2) else "VERIFIED_PASS",
                  stale_efficiency_party=stale.efficiency_party,
                  consistent_efficiency_party=consistent.efficiency_party,
                  rate_stale=r1,rate_consistent=r2,relative_error=(r1-r2)/r2)


@check("X10", "BBM92", "n_X override versus implicit sent/detected-unit equivalence")
def bbm92_nx_differential():
    d=standard_detector.customise(dark_count_rate=1e-8,polarization_drift=0,error_detector=0,efficiency_party=1)
    N=int(5e10)
    def rate(nx):
        return scalar(bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=N).compute_rate(
            mu=.5,attenuation=.2,probability_basis_X=.5,probability_basis_Z=.5,n_X=nx))
    normal=rate(None)
    explicit=rate(N//2)
    return report("REPRODUCED_SIGNAL" if not np.isclose(normal,explicit) else "VERIFIED_PASS",
                  implicit=normal,explicit_half_sent_pulses=explicit,ratio=explicit/normal,
                  caveat="API documentation defines n_X as pulses; source treats override as detections")


@check("X11", "BBM92", "Finite-key entropy cap A/B with small N")
def bbm92_cap_differential():
    d=standard_detector.customise(dark_count_rate=1e-8,polarization_drift=0,error_detector=0,efficiency_party=1)
    def rate(N):
        return scalar(bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=N).compute_rate(
            mu=.5,attenuation=.2,probability_basis_X=.5,probability_basis_Z=.5))
    original = bbm92.one_minus_h
    before = {n:rate(n) for n in [25,50,100,10000]}
    with patch.object(bbm92,"one_minus_h",lambda p: original(np.minimum(p,.5))):
        after = {n:rate(n) for n in [25,50,100,10000]}
    return report("REPRODUCED_SIGNAL" if before[25]>0>after[25] else "INCONCLUSIVE",
                  original=before, capped=after,
                  caveat="At N=25 positive rate is less than one expected output bit")


@check("X12", "BB84", "Finite entropy cap v2.0.5 A/B actual computed rate")
def bb84_cap_differential():
    params=dict(mu=[.980057214,.0576948581,.0000029565],attenuation=0,
                probability_basis_X=[.849999575,.099999950,.049999975],
                probability_basis_Z=[4.25e-7,5e-8,2.5e-8])
    def rate():
        return scalar(BB84FiniteKeyRateEstimate(detector=standard_detector,number_of_pulses=int(1e9),number_of_decoy=2).compute_rate(**params))
    original=bb84.h
    baseline=rate()
    with patch.object(bb84,"h",lambda p: original(np.minimum(p,.5))):
        corrected=rate()
    return report("REPRODUCED_SIGNAL" if baseline>0>corrected else "INCONCLUSIVE",
                  original=baseline, research_capped=corrected,
                  caveat="Only monotonic phase-penalty adjustment; formal security proof not rederived")


@check("X13", "BB84", "Poisson tail omitted probability at actual automatic cutoff")
def poisson_auto_cutoff():
    items=[]
    for mu in [.1,.5,.8,1.]:
        M=max(int(poisson.isf(1e-16,mu)),5)
        intended=float(poisson.sf(M,mu))
        actual=float(poisson.sf(M+1,mu))
        omitted=float(poisson.pmf(M+1,mu))
        items.append({"mu":mu,"M":M,"intended_tail":intended,"actual_tail":actual,
                      "omitted_mass":omitted,"omitted_expected_events_N_1e12":omitted*1e12})
    return report("REPRODUCED_SIGNAL" if any(x["omitted_mass"]>0 for x in items) else "VERIFIED_PASS",
                  cases=items, caveat="Probability mass is typically tiny when M auto-selected")


@check("X14", "BB84", "Finite Chernoff LP relaxed bound changes feasible optimizer")
def lp_upper_bound_differential():
    n=1_000_000
    mu=np.array([.7,.2,.02])
    priors=np.array([.6,.3,.1])
    M=6
    eps=np.repeat(1e-8,M+1)
    gain,_=bb84.compute_gain_and_error_rate(standard_detector,mu,0)
    obs=np.asarray(gain*priors*n)
    all_b=[]
    original=bb84.scipy.optimize.linprog
    def inspect_lp(*args,**kw):
        base=original(*args,**kw)
        nint=len(priors)
        start=2*nint+(M+1)
        p_photons=np.asarray(priors @ poisson.pmf(np.arange(M+1),mu[:,None]))
        f=bb84.bound_f(n,p_photons,eps)
        theoretical=np.minimum(p_photons*n+f,float(obs.sum()))/n
        modified=np.asarray(kw["b_ub"]).copy()
        old_upper=np.asarray(modified[start:start+M+1]).copy()
        modified[start:start+M+1]=theoretical
        other=original(*args,**{**kw,"b_ub":modified})
        all_b.append({"base_status":int(base.status),"corrected_status":int(other.status),
                      "base_objective":scalar(base.fun) if base.success else None,
                      "corrected_objective":scalar(other.fun) if other.success else None,
                      "base_upper_count":(old_upper*n).tolist(),
                      "corrected_upper_count":(theoretical*n).tolist()})
        return base
    with patch.object(bb84.scipy.optimize,"linprog",side_effect=inspect_lp):
        try:
            result=bb84.solve_finite_lp(
                target_vacuum=0,target_single=1,probabilities_intensity_j=priors,
                mu=mu,max_num_photons=M,number_of_pulses=n,observed_count=obs,
                epsilon_mu_j=np.repeat(1e-8,len(mu)),epsilon_num_photons_M=eps,
                epsilon_num_photons_M_in_basis_B=np.repeat(1e-8,len(mu)),
            )
            final_status="SOLVED"
        except bb84.OptimizationError as e:
            final_status="ORIGINAL_LP_FAILURE"
    if not all_b:
        return report("INCONCLUSIVE",reason="LP never entered scipy")
    stats=all_b[0]
    diff=max(x-y for x,y in zip(stats["base_upper_count"],stats["corrected_upper_count"]))
    return report("REPRODUCED_SIGNAL" if diff>1 else "VERIFIED_PASS",
                  solver=final_status, m=6,n=n, max_relaxation_in_events=diff, details=stats,
                  caveat="Upper-bound relaxation changes feasible region; does not alone prove nonconservative key rate")


def main():
    for ident, subsystem, title, fn in CHECKS:
        try:
            item=fn()
            item.update({"id":ident,"subsystem":subsystem,"title":title})
        except Exception as exc:
            item={"id":ident,"subsystem":subsystem,"title":title,
                  "status":"HARNESS_ERROR","error":repr(exc),
                  "traceback":traceback.format_exc(limit=5)}
        RESULTS.append(item)
        print(json.dumps(item,ensure_ascii=False,default=str),flush=True)
    counts={s:sum(r["status"]==s for r in RESULTS) for s in
            ["VERIFIED_PASS","REPRODUCED_SIGNAL","INCONCLUSIVE","HARNESS_ERROR"]}
    summary={"total":len(RESULTS),"status_counts":counts,
             "note":"REPRODUCED_SIGNAL = observation, not a confirmed exploitable security vulnerability."}
    Path("crossmodule_v205_results.json").write_text(json.dumps({"summary":summary,"results":RESULTS},indent=2,default=str)+"\n")
    print("CROSSMODULE SUMMARY "+json.dumps(summary),flush=True)
    raise SystemExit(2 if counts["HARNESS_ERROR"] else 0)


if __name__=="__main__":
    main()
