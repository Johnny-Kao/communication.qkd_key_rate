"""Independent four-issue research proofs on *unmodified* TNO v2.0.5.

No production patch. All public transcript/data is synthetic; the Winnow
transcript study includes both parties' parity/syndrome messages, yielding
a conservative upper bound on publicly observable linear information.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import os
import textwrap
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
from tno.quantum.communication.qkd_key_rate.classical import Message, Permutations, Schedule
from tno.quantum.communication.qkd_key_rate.classical.winnow import WinnowCorrector, WinnowReceiver, WinnowSender
from tno.quantum.communication.qkd_key_rate.quantum import Detector, standard_detector
from tno.quantum.communication.qkd_key_rate.quantum import bbm92
from tno.quantum.communication.qkd_key_rate.quantum.bb84 import (
    BB84FiniteKeyRateEstimate, BB84FullyAsymptoticKeyRateEstimate,
)

DATA=[]

def item(name, category, **details):
    out={"id":name,"classification":category,**details}
    DATA.append(out)
    print(json.dumps(out, default=str, ensure_ascii=False), flush=True)

def numeric(x):
    return float(np.asarray(x).item())

def code_literals(function, *vars):
    tree=ast.parse(textwrap.dedent(inspect.getsource(function)))
    nodes={}
    for n in tree.body[0].body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            try:nodes[n.targets[0].id]=ast.literal_eval(n.value)
            except (ValueError,TypeError,SyntaxError):pass
    return {k:nodes[k] for k in vars}

def security_math():
    p=code_literals(BB84FiniteKeyRateEstimate.compute_rate,
        "epsilon_security","epsilon","epsilon_correct","epsilon_1","epsilon_2","epsilon_3",
        "epsilon_single_photon")
    sec=p["epsilon_security"];eps=p["epsilon"]
    margin=sec-eps
    is_valid=margin>0
    base_term=p["epsilon_correct"] * (p["epsilon_2"]*p["epsilon_3"]*margin)**2
    mirrored_sec=2*eps-sec
    mirrored_margin=mirrored_sec-eps
    mirror_term=p["epsilon_correct"]*(p["epsilon_2"]*p["epsilon_3"]*mirrored_margin)**2
    # The equation is invariant under flipping the margin sign because it is squared,
    # but the LEFTOVER HASH LEMMA requires positive epsilon_sec-epsilon.
    sec_paper=2**-50
    eps_paper_upper=2**-52
    paper_margin=sec_paper-eps_paper_upper
    # At a minimum epsilon must cover the 2*eps1+eps2+eps3 term.
    minimal_epsilon=2*p["epsilon_1"]+p["epsilon_2"]+p["epsilon_3"]
    item("Q02","PROOF_DOMAIN_VIOLATION",
        source_params=p,margin=margin,epsilon_exceeds_security_factor=eps/sec,
        required_domain="0 <= epsilon < epsilon_security",
        minimal_epsilon_components=minimal_epsilon,
        negative_margin_mirrored_in_squared_expression=math.isclose(base_term,mirror_term,rel_tol=1e-12),
        source_privacy_loss_log2=math.log2(base_term),
        paper_example={"epsilon_security":sec_paper,"epsilon_upper":eps_paper_upper,"positive_margin":paper_margin},
        observed=(not is_valid) and base_term>0 and paper_margin>0,
        note="Definite mismatch to original 2021 paper Eq. 11/22/39; independently rederive total budget before proposing concrete numeric replacements.")

def detector_math():
    kw=dict(name="synthetic",jitter_source=0.,jitter_detector=0.,
            dead_time=1e-7,detection_window=1.,dark_count_rate=1e-8,interval=1e-7)
    initial=Detector(**kw,efficiency_system=.5,efficiency_detector=.2)
    stale=initial.customise(efficiency_system=.8)
    recomputed=Detector(**kw,efficiency_system=.8,efficiency_detector=.2)
    initial_rate=numeric(BB84FullyAsymptoticKeyRateEstimate(detector=initial).compute_rate(mu=.5,attenuation=.2))
    stale_rate=numeric(BB84FullyAsymptoticKeyRateEstimate(detector=stale).compute_rate(mu=.5,attenuation=.2))
    correct_rate=numeric(BB84FullyAsymptoticKeyRateEstimate(detector=recomputed).compute_rate(mu=.5,attenuation=.2))
    reverse=""
    try:initial.customise(efficiency_system=.2)
    except Exception as e:reverse=type(e).__name__+":"+str(e)
    d=Detector(**dict(kw,name="dark",efficiency_system=1.,efficiency_detector=.2,interval=.0001, dark_count_rate=.00001,dark_count_frequency=10.))
    item("D01","DEFINITE_INTERNAL_INVARIANT",
         original_party=initial.efficiency_party,
         stale_party=stale.efficiency_party,
         mathematically_expected_party=.8*.2,
         fresh_party=recomputed.efficiency_party,
         baseline_rate=initial_rate,stale_rate=stale_rate,
         correct_reconstructed_rate=correct_rate,
         relative_deviation=(stale_rate-correct_rate)/correct_rate,
         reverse_override_rejection=reverse,
         accepted_dark_count_rate=d.dark_count_rate,
         implied_dark_count_rate=d.dark_count_frequency*d.interval,
         observed=(stale.efficiency_party!=.8*.2 and abs(stale_rate-correct_rate)>1e-4
                   and reverse.startswith("ValueError")),
         note="Constructor documents required efficiency_party=efficiency_system*efficiency_detector. customise carries stale computed value; one-sided check accepts decreases but rejects increases. Same sign mistake for dark_count fields.")

def bbm92_math():
    d=standard_detector.customise(dark_count_rate=1e-8,polarization_drift=0,error_detector=0,efficiency_party=1)
    N=int(5e10);mu=.5;loss=.2
    gain,_=bbm92.compute_gain_and_error_rate(d,d,loss/2,loss/2,mu/2)
    gain=numeric(gain)
    def calc(px, nx):
        est=bbm92.BBM92FiniteKeyRateEstimate(detector=d,number_of_pulses=N)
        try:
            r=est.compute_rate(mu=mu,attenuation=loss,probability_basis_X=px,probability_basis_Z=1-px,n_X=nx)
            return {"rate":numeric(r)}
        except Exception as e:return {"error":type(e).__name__,"message":str(e)[:110]}
    result={
        "implicit_px_half":calc(.5,None),
        "explicit_detected_x_count":calc(.5,gain*N*.5),
        "explicit_sent_x_count":calc(.5,N//2),
        "zero_x_basis_no_override":calc(0,None),
        "zero_x_basis_but_positive_nx_override":calc(0,N//2),
        "all_x_basis_but_2x_more_nx_than_pulses":calc(1,2*N),
    }
    a=result["implicit_px_half"].get("rate"); b=result["explicit_detected_x_count"].get("rate")
    c=result["explicit_sent_x_count"].get("rate");z=result["zero_x_basis_but_positive_nx_override"].get("rate")
    item("B03","DOCUMENTED_API_UNITS_MISMATCH",
         N=N,gain=gain,units_documented_in_source="n_X: Number of pulses in the X-basis",
         expected_detected_events=gain*N*.5,
         cases=result, ratio_explicit_sent_vs_implicit=(c/a if a and c else None),
         observed=(a is not None and b is not None and c is not None and z is not None
                   and np.isclose(a,b,rtol=1e-12) and c>2*a and z>0),
         note="No override -> gain*P_X*N DETECTED events. Override docs say SENT pulses but code treats as detected. With zero X probability an override alone can invent a positive key. Needs parameter contract or validation change, not necessarily core optimizer flaw.")

def gf2_rank(matrix):
    a=np.asarray(matrix,dtype=np.uint8).copy() % 2
    count=0
    for col in range(a.shape[1]):
        if count>=a.shape[0]:break
        nz=np.flatnonzero(a[count:,col])
        if not len(nz):continue
        p=count+int(nz[0])
        if p!=count:a[[count,p]]=a[[p,count]]
        rows=np.flatnonzero(a[:,col])
        rows=rows[rows!=count]
        for r in rows:a[r]^=a[count]
        count+=1
    return count

def run_winnow(basis_index: int|None,repair:bool=False,repair_parity:bool=False):
    # Uses a fixed error position independent of the secret key. Hence the
    # complete protocol transcript/output is an affine map of the 512 key bits.
    n=512
    key=[0]*n
    if basis_index is not None:key[basis_index]=1
    counterpart=key.copy();counterpart[300]^=1
    # Supply a spare, deterministic permutation. A single pass triggers
    # Winnow's implicit unseeded random-permutation augmentation.
    perms=Permutations([list(range(n)), list(range(n))])
    logs=[]
    prev_agreement=WinnowReceiver.disagreeing_block_parities
    prev_build_syndromes=WinnowReceiver.build_syndrome_string
    prev_drop=WinnowSender.discard_syndrome_bits
    prev_parity_drop=WinnowSender.discard_parity_bits
    def publicly_sent_parity(self,alice):
        # This is Bob's actual parity string sent in the current round,
        # not unsent parity precomputed for a future round.
        result=prev_agreement(self,alice)
        logs.extend(int(bit) for bit in self.parity_string)
        return result
    def publicly_sent_syndrome(self,alice):
        # The algorithm records Bob's syndrome on Alice's object; one side
        # communicates it. Omitting the locally recomputed counterpart avoids
        # double-counting private values as transcript.
        result=prev_build_syndromes(self,alice)
        for syndrome in alice.syndrome_array[:alice.number_of_bad_blocks]:
            logs.extend((int(syndrome)>>j)&1 for j in range(self.syndrome_length))
        return result
    def parity_drop(self):
        if not repair_parity:return prev_parity_drop(self)
        original_block_size=self.block_size
        # Remove exactly one original parity pivot per complete block.
        for block in range(self.number_of_blocks-1,-1,-1):
            self.message.pop(block*original_block_size)
            self._net_exposed_bits-=1
        self.block_size-=1
        self.transcript+="Research-only full parity drop (not product code).\n"
    def drop(self):
        if not repair:return prev_drop(self)
        if not self.number_of_bad_blocks:return None
        positions=[]
        for block in self.bad_blocks_array[:self.number_of_bad_blocks]:
            for power in range(self.syndrome_length):
                local=(1<<power)-1
                if local<self.block_size:
                    positions.append(block*self.block_size+local)
        for p in sorted(positions,reverse=True):
            self.message.pop(p)
            self._net_exposed_bits-=1
        self.transcript+="Research-only syndrome pivot drop (not product code).\n"
        return None
    # Record only messages which the actual reconciliation round exchanges;
    # do not count the next pass' precomputed, but unsent, parity string.
    with patch.object(WinnowReceiver,"disagreeing_block_parities",publicly_sent_parity), \
         patch.object(WinnowReceiver,"build_syndrome_string",publicly_sent_syndrome), \
         patch.object(WinnowSender,"discard_syndrome_bits",drop), \
         patch.object(WinnowSender,"discard_parity_bits",parity_drop):
        a=WinnowSender(Message(key),perms,Schedule([1]))
        b=WinnowReceiver(Message(counterpart),perms,Schedule([1]))
        outcome=WinnowCorrector(a,b).correct_errors()
    return (np.asarray(logs,dtype=np.uint8),
            np.asarray(outcome.output_alice.message,dtype=np.uint8),
            {"same_outputs":bool(outcome.output_alice==outcome.output_bob),
             "error_rate":float(outcome.output_error),
             "length":outcome.output_length,
             "net_exposed_bits":int(outcome.number_of_exposed_bits)})

def winnow_matrix(mode:str):
    repair=mode in ("correct_pivots","correct_all")
    repair_parity=mode=="correct_all"
    reference_T,reference_O,reference_info=run_winnow(None,repair,repair_parity)
    count=512
    if os.getenv("QKD_SMOKE")=="1":count=16
    t=np.empty((len(reference_T),count),dtype=np.uint8)
    o=np.empty((len(reference_O),count),dtype=np.uint8)
    for i in range(count):
        result_T,result_O,info=run_winnow(i,repair,repair_parity)
        if len(result_T)!=len(reference_T) or len(result_O)!=len(reference_O):
            raise RuntimeError(f"transcript/output lengths unstable: {mode} {i}")
        t[:,i]=result_T^reference_T
        o[:,i]=result_O^reference_O
    t_rank=gf2_rank(t)
    o_rank=gf2_rank(o)
    union_rank=gf2_rank(np.vstack((t,o)))
    overlap=t_rank+o_rank-union_rank
    return {
        "mode":mode, "message_bits_spanned":count,
        "public_transcript_bits_recorded":len(reference_T),
        "output_bits":len(reference_O),
        "rank_transcript":t_rank,"rank_output":o_rank,"rank_union":union_rank,
        "linear_information_shared_by_transcript_and_retained_output":overlap,
        "end_to_end":reference_info,
        "zero_message_output_sha256":hashlib.sha256(reference_O.tobytes()).hexdigest()[:16],
        "caveat":"Only first-round transmitted Bob parity and syndrome; excludes final precomputed unsent parities. Fixed error position, one schedule; information is conditional on known error pattern."
    }

def winnow_math():
    before=winnow_matrix("upstream")
    after=winnow_matrix("correct_pivots")
    all_fixed=winnow_matrix("correct_all")
    item("W01","TESTED_PUBLIC_TRANSCRIPT_RANK",
         original=before, corrected_syndrome_only=after, corrected_syndrome_and_parity=all_fixed,
         original_public_info_vs_tracked_exposure=[before["linear_information_shared_by_transcript_and_retained_output"],before["end_to_end"]["net_exposed_bits"]],
         net_exposure_conservative_in_example=(before["linear_information_shared_by_transcript_and_retained_output"] <= before["end_to_end"]["net_exposed_bits"]),
         observed=before["linear_information_shared_by_transcript_and_retained_output"] >
                  after["linear_information_shared_by_transcript_and_retained_output"],
         note="Quantifies disclosed linear information about retained key for one fixed pattern. Compare to net_exposed_bits: this run is conservative, so not proof of final-key compromise.")

def winnow_parity_math():
    cases=[]
    for n in [8,16,32,64,128,512,1024]:
        sender=WinnowSender(Message([0]*n),
            Permutations([list(range(n)),list(range(n))]),Schedule([1]))
        expected=n//8
        actual=n-sender.message.length
        cases.append({"N":n,"expected_full_block_parity_deletions":expected,
                      "actual_removed":actual,"undropped":expected-actual,
                      "tracked_net_exposed":sender.net_exposed_bits})
    item("W02","PARITY_DELETION_LOOP_LENGTH_SHRINK",
         cases=cases,observed=all(c["tracked_net_exposed"]==c["undropped"] for c in cases) and any(c["undropped"]>0 for c in cases),
         note="Loop termination compares old_index to shrinking self.message.length. It fails the documented first-bit-per-block deletion for longer messages, but the exposure counter accounts for undropped bits.")

def main():
    for ident,fn in [("Q02",security_math),("D01",detector_math),("B03",bbm92_math),("W01",winnow_math),("W02",winnow_parity_math)]:
        try:fn()
        except Exception as e:
            item(ident,"HARNESS_ERROR",error=repr(e),traceback=traceback.format_exc(limit=7))
    status={"tested_ids":[r["id"] for r in DATA],
            "reproduced":sum(r.get("observed") is True for r in DATA),
            "not_reproduced":sum(r.get("observed") is False for r in DATA),
            "harness_error":sum(r.get("classification")=="HARNESS_ERROR" for r in DATA)}
    Path("four_issue_proof_results.json").write_text(json.dumps({"summary":status,"evidence":DATA},indent=2,default=str)+"\n")
    print("FOUR ISSUE SUMMARY",json.dumps(status),flush=True)
    raise SystemExit(2 if status["harness_error"] else 0)

if __name__=="__main__":
    main()
