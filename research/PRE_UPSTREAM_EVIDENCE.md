# TNO QKD v2.0.5 — four-commit pre-upstream evidence

**Fork:** Johnny-Kao/communication.qkd_key_rate (public).
**Base:** official v2.0.5, `7266c35e38ebc52bf9542649963a8a0a613cb8c6`.
**Candidate:** `staging/qkd-v205-four-fixes-pr-ready`. A single proposed PR, four independently reviewable commits. **No PR has been opened; no upstream writes.**

## Four focused commits

| Commit scope | Corrected behavior | New regression checks |
|---|---|---|
| Detector | Recompute dependent efficiency on system changes, consistently reject mismatched efficiency and dark counts, preserve physical dark count frequency across interval changes | 4 tests RED on official v2.0.5; GREEN on staging |
| BBM92 | Treat explicit `n_X` as **sent pulses**, as documented and as in BB84; apply gain consistently; reject impossible overrides | 6 tests RED on official; GREEN on staging |
| Winnow | Drop one parity pivot per original complete block; remove syndrome pivot bits from each flagged block in reverse-index order | 5 tests RED on official; GREEN on staging; full Alice/Bob reconciliation |
| BB84 finite security budget | Use paper's `2**-50` secrecy/correctness/abort levels, `2**-55` smoothing levels, and `2**-60` per-LP concentration bounds. Compute a conservative failure budget over all three LPs. Reject nonpositive secrecy remainder. Use Poisson tail `P(K>M)` for truncated `0..M` states. | 7 new tests RED on official; GREEN on staging. No expected failures remain. |

### BB84 mathematical basis

Paper: Attema, Bosman and Neumann, *Optimizing the decoy-state BB84 QKD protocol parameters* (2021), [Section 6.2; Eqs. (11), (22), (38) and (39)](https://link.springer.com/article/10.1007/s11128-021-03078-0).

Eq. (39) requires a positive `epsilon_security-epsilon` with a total smoothing/statistical allocation
`epsilon=2*epsilon_1+epsilon_2+epsilon_3+epsilon_e+epsilon_X+epsilon_MX+epsilon_MZ`.

The v2.0.5 source used `epsilon_security=2e-50`, `epsilon=1e-7`, `epsilon_1..3=2e-55`, and per-LP statistical bounds `1e-8`, not the powers of two used in the paper. The logarithmic penalty squares the invalid negative margin without raising an error.

For fixed max photon number `M` and intensity count `J`, the staging implementation uses `epsilon_lp=2**-60` for every LP concentration/tail event and allocates a **conservative union bound** across two Z programs and one X program:

`epsilon_e <= 2*(M+1+J)*epsilon_lp`

`epsilon_X <= (M+1+J)*epsilon_lp`

`epsilon_truncation <= 3*J*epsilon_lp`

`epsilon_total = 2*epsilon_1 + epsilon_2 + epsilon_3 + epsilon_e + epsilon_X + epsilon_truncation`.

Both the key-rate LP objective and its final phase error term use `epsilon_1` for the same sample-bound parameter. The code rejects `epsilon_total >= epsilon_security`. Counting all three LP bounds separately is deliberately more conservative than deduplicating shared statistical events.

The `solve_finite_lp` tail originally used `poisson.sf(M+1)` (counts `K>M+1`), whereas `0..M` truncation requires `poisson.sf(M)` (counts `K>M`). This is corrected in the same BB84 commit because the proof budget depends on a valid concentration bound for the entire omitted tail.

**Scope limit:** this patch establishes the documented **failure-probability accounting** and corrects the omitted Poisson tail. It does **not** constitute a new complete independent proof of all BB84 LP mathematics or resolve the separately tracked entropy-cap issue (#2).

### RED/GREEN and full-suite verification

All new regression suites are run against **unmodified official v2.0.5** and the candidate on the same GitHub Actions runner. GC matrix: Ubuntu 24.04, Python 3.11/3.12/3.13; raw dependency freeze, native logs, test counts and each baseline RED log retained.

The official `test_required_linktime` BBM92 nonlinear optimizer has historically produced intermittent native-suite failures even with unmodified source. When native GC fails, compare official and staged failed test IDs **within the same Python/run** before attributing a regression to the candidate. A red overall GC status must not be misrepresented as success.

### PR discussion

One PR, four commits, each independently reviewable. Suggested opening: briefly thank the maintainers for v2.0.5 and the additional LP correction they identified, then explain that a follow-up review against the original security proof uncovered related correctness discrepancies. The PR body should show the four changes, exact RED/GREEN evidence and any compatibility impact.

- **BBM92 compatibility:** users who passed observed detections rather than documented *sent* pulse count to `n_X` will see different results.
- **Winnow security claim:** the identified deletion issues affect output/key retention; one fixed-pattern GF(2) experiment found the current net disclosed-bit accounting conservative. Do not claim a verified key-exposure exploit.
- **BB84 proof qualification:** failure-budget correctness is verified under the cited LP confidence-bound model, but not a full independent audit of every underlying LP constraint.
- **Upstream status:** no PR or interaction until explicit contributor approval.
