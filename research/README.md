# TNO QKD v2.0.5 — four-issue deep dive

**Baseline:** TNO official v2.0.5, commit `7266c35e38ebc52bf9542649963a8a0a613cb8c6`.
**Scope:** fork research, synthetic only. No production-source changes, TNO upstream PR/issue/comment/push.
**GC:** Ubuntu 24.04 Python 3.12 and 3.13; complete native suite plus independent numerical/contract/GF(2) comparison. Native failures remain visible.

## Results under investigation

- **Q02 (BB84 finite):** Code sets `epsilon_security = 2e-50` and `epsilon = 1e-7`. Their difference is negative, outside the positive-margin hypothesis in the cited security proof (Attema et al. 2021, Eqs. 11, 22, 39). The squared expression conceals the sign. Do not select new parameters before rederiving the *whole* failure budget. Distinguish decimal `2e-50` from mathematical `2**-50`.
- **B03 (BBM92):** Documentation labels `n_X` as number of pulses. Internal default uses `gain * probability_basis_X * N` (detections), whereas caller override uses the raw supplied value. A reasonable sent-pulse count gives a ~2.87x rate difference; X-basis probability 0 with a positive override yields a positive rate. Correctness is clear for contradictory inputs; proper fix depends on API intention.
- **D01 (Detector):** `customise(efficiency_system=.8)` may retain stale `efficiency_party=.1` with `efficiency_detector=.2`, violating the documented product relation `.16`. BB84 key rate differs by 37.7% from consistently reconstructed Detector. Check the one-sided consistency comparison and related dark-count pair.
- **W01/W02 (Winnow):** `discard_syndrome_bits` omits flagged-block offset; `discard_parity_bits` stops at shrinking message length. For 512-bit initial message, 64 parity bits disclosed but only 57 parity pivot bits dropped. Full GF(2) linear mapping of actually transmitted first-round parity+syndrome and final retained key with fixed error position: upstream 8 independent transcript constraints on retained key; syndrome-only pivot repair 6; repair both parity and syndrome 0. **But upstream tracks `net_exposed_bits=12`, which is conservative in this particular scenario. No confirmed final-key breach.** Tests fix random permutation inputs and omit unsent future-round parity. Production code is never patched.

## Classification rules

- 'Observed' means a synthetic code-level reproducible result, not deployed vulnerability or CVE.
- A question to maintainers must distinguish mathematical domain violations, parameter validation issues, correctness/efficiency problems and unproven security exploitation.
- Before proposing Q02 numeric code patch, rederive epsilon_X, epsilon_e and truncation budgets. Before claiming Winnow security flaw, show a trace where true disclosed rank exceeds the accounted leak, or identify a documented guarantee violated.

**Paper:** https://link.springer.com/article/10.1007/s11128-021-03078-0
