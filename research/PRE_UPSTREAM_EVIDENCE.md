# TNO QKD v2.0.5 — pre-upstream staging evidence

**Fork:** Johnny-Kao/communication.qkd_key_rate (public).
**Base:** TNO v2.0.5 / commit `7266c35e38ebc52bf9542649963a8a0a613cb8c6`.
**Staging:** `staging/qkd-v205-four-correctness-prepr`.
**Authorization:** staging and research on Johnny-Kao fork only. **No new upstream PR, issue, comment, or push.**

## Change and review boundaries

This is one **temporary integration branch** containing separate commits so each fix can be reviewed independently. It is **not a recommendation** to open a single upstream PR covering four unrelated modules.

| Topic | Code state | Regression evidence | Pre-upstream decision |
|---|---|---|---|
| Detector D01 | Implemented | Partial customization recomputes party efficiency; reject inconsistent efficiency/dark-count in both directions; preserve dark count per second when interval changes. | Small standalone PR candidate |
| BBM92 B03 | Implemented per documented API | Treat explicit `n_X` as **sent pulses**, apply detector gain; reject contradictory zero/all-X counts and out-of-range counts; return zero when no X pulses. | Separate PR; **could affect callers passing detected counts** |
| Winnow W01/W02 | Implemented | Remove one parity pivot per complete block; remove syndrome pivots from flagged blocks in descending original-position order; Alice/Bob remain consistent in end-to-end correction. | Separate PR with syndrome/parity tests |
| BB84 Q02 security budget | **NOT patched** | Explicit reproduction test for negative `epsilon_security-epsilon`, plus strict **expected-failure (xfail)** for theorem-required budget invariant. | **BLOCKED**: no arbitrary constants until complete security proof budget including LP/statistical bounds is rederived and reviewed |

## Red/green evidence

On unmodified official v2.0.5, the new tests reproduce **4 Detector failures, 6 BBM92 failures, 5 Winnow failures** with deterministic cases; the remaining Winnow checks on baseline pass. On patched staging, those regression suites passed locally. This separation proves the tests are not merely tautologies.

The **BB84 Q02 expected-failure is intentional**, not a claimed passing security test. The source sets `epsilon_security=2e-50`, `epsilon=1e-7` and then squares their negative difference inside the key-rate penalty. The reference derivation also relates `epsilon` to `2*epsilon_1+epsilon_2+epsilon_3`; changing one constant alone could still break the mathematical contract. Source reference: [Attema et al. 2021, Eqs. 11 and 22–23](https://link.springer.com/article/10.1007/s11128-021-03078-0). This is a **validity-of-security-bound** concern, not evidence of a deployed exploit.

**Local full suite** (macOS Python 3.13): `122 passed, 1 xfailed`, 5 warnings. GitHub Actions verifies Python 3.11/3.12/3.13, both original and staging full suites, and baseline-red/new-green evidence. Official `test_required_linktime` optimizer behavior was previously intermittent: do not classify a red native job as a defect introduced by a staged fix without baseline comparison.

## Discussion before any upstream PR

1. **Avoid bundling** Detector, BBM92, Winnow and BB84 into one upstream PR: different contracts and reviewer expertise. The staging branch is a test aggregator, not upstream scope.
2. **Prefer first PR: Detector**: narrow numerical invariant, deterministic reproduced result, clear test evidence, minimal mathematical review.
3. **BBM92:** explicit `n_X` behavior changes for callers treating it as detected count even though docs say sent pulses. Ask whether backwards compatibility warrants deprecation or an `n_X_observed` parameter; this affects the best upstream patch format.
4. **Winnow:** report *correctness and retention efficiency*, **not a confirmed key leakage vulnerability**. Earlier GF(2) example measured 8 independent transcript constraints on retained key versus 12 accounted; the scenario's existing accounting is conservative.
5. **BB84 security budget:** a maintainer-facing issue/discussion needs the full epsilon allocation first. **Do not ship a guessed "security fix".** Keep a clear strict-xfail diagnostic, not a failing product package by default.
6. Keep four commits separate to allow selecting/cherry-picking just the approved topic into a clean final upstream branch after review.

## Verification

After pushing to Johnny-Kao fork, link the exact GC run here and lock per-version suite results, as well as dependency versions and baseline RED logs. Do not create a PR or contact TNO until instructed.
