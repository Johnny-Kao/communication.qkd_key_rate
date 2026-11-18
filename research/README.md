# TNO QKD v2.0.5 — One-shot Global Correctness Sweep (Research)

**Base:** exact TNO release `v2.0.5` / `7266c35e38ebc52bf9542649963a8a0a613cb8c6`.
**Repo/branch:** Johnny-Kao fork, `research/qkd-v205-global-gc`.
**Permission:** Research only. No code modification to TNO, no upstream submission, no PR.
**Scope:** 18 non-test modules (quantum protocols, detectors, LP helpers, classical error-correction, privacy amplification and shared entropy), plus full native tests.
**Environment:** one GitHub Actions-hosted Linux job, all synthetic inputs.

## Candidate-first verification matrix

| ID | Code surface | Symptom checked | Interpretation gate |
|---|---|---|---|
| Q01 | BB84 finite entropy | upper confidence bound >0.5 passes into h | proof-defined capped entropy, known #2 |
| Q02 | BB84 finite security parameters | epsilon_security - epsilon <0, squared away | Attema 2021 Eq (11)/(39), positive secrecy budget required |
| Q03 | BB84 solve_finite_lp | `f(N,p,eps)` count bound multiplied by N again | Attema Eq (30)/(31); loosening may only decrease rate |
| Q04 | BB84 LP Poisson tail | `sf(M+1)` used where P(X>M)=`sf(M)` | assess true tail mass under realistic cutoff |
| Q05 | BB84 zero Z basis | invalid normal path fallback / exception | incomplete input handling, low-priority |
| B01 | BBM92 finite pZ=0 | still returns positive key-rate | model-derived QBER vs actual PE sample contract |
| B02 | BBM92 finite h | phase upper error >0.5 yet positive rate | actual usable integer key and theoretical proof needed |
| B03 | BBM92 finite n_X override | sent pulses vs detected events units | documented public API vs implementation |
| D01 | Detector customize | inconsistent efficiency accepted; rate differs | real downstream silent wrong result |
| D02 | Detector dark count | inconsistent rate/frequency accepted | one-sided validation |
| W01 | Winnow discards | flagged block offsets not applied | actual disclosed-syndrome secrecy not yet proven |
| W02 | Winnow equality blind spot | output error=0 despite wrong deletions | original integration test incapable of seeing leak |
| W03 | Winnow get_syndrome | end index guard is > not >= | public helper boundary; normal reachability unknown |
| C01 | Cascade ParityStrategy | 0.15 table entry rejected due strict > | low priority |
| C02 | Cascade prior error subrange | denominator full length | debug-only impact |
| P01 | PrivacyAmplification SHAKE | fixed deterministic hash, output > entropy allowed | no proven information-theoretic PA guarantee |
| M01 | Message mutation | accepts non-binary value | low priority unless reachable normally |

## Evaluation rules

- `REPRODUCED_SIGNAL` means a synthetic observation, **not** a confirmed exploitable vulnerability, security guarantee violation or deployment impact.
- `NOT_REPRODUCED` and `HARNESS_ERROR` remain visible in JSON. The latter is an experiment failure requiring correction, not proof that source code is safe.
- The workflow does **not** silently apply proposed product patches. Selective A/B monkeypatches are named and contained inside an isolated probe.
- Official test suite runs on unmodified TNO v2.0.5 source; our additions are only `research/` and the research-only workflow.
- Save one set of raw logs and machine-readable evidence. Do not automatically raise PRs or publish security advisories.
- Q02–Q04 are not assumed high-impact before reference-model validation.
- This is a source-wide candidate scan and bounded practical test matrix, **not** formal proof of every code path.

## Mathematical references

- Attema, Bosman & Neumann, [Optimizing the decoy-state BB84 QKD protocol parameters](https://link.springer.com/article/10.1007/s11128-021-03078-0): Eq. (22)–(23), (30)–(31), (39). In Eq. (39) and §6.2 epsilon_sec must exceed the aggregate failure budget; Eq. (31) uses count-scale `f(N,p,epsilon)`, without multiplying by N again.
