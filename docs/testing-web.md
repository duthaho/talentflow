# Web component tests under CPU contention

**Status: not stabilized under heavy shared-runner load; accepted as documented.**
Follow-up experiments did not validate a safe fix at the observed shared-runner
pressure. Their code/environment changes were reverted; the follow-up retains
measurement and evidence improvements only. No reserved CPU window was available,
so the project owner accepted the loaded-timing results as known risk (see
[Acceptance decision](#acceptance-decision)).

DUTH-125 investigates the feedback timeout first observed on DUTH-54 / PR #27
(`636d4fa6efa90d0eb883349dff37fd0d40c6a96a`). The follow-up starts from
`1bf5766` on Linux ARM64, Node 22.22.2, with two available CPUs. The load helper
used Python 3.12.3; the backend check used Python 3.13.18.

## Cause and scope

The feedback test has a five-second wall-clock budget. Its accessible queries,
dialog interactions and input simulation all consume that budget. The 41-character
`userEvent.type` fixture dispatches keyboard/input events and yields to a timer for
each character; the textarea also updates React state for its character counter.
Under contention, scheduler delays accumulate even though the fake API answers
in memory. This is test execution cost, not a slow HTTP response.

A diagnostic run reached the comment input at 4,450 ms and timed out at 5,214 ms
before typing completed. A separate isolated run timed out at 5,135 ms. Thus typing
is not the sole cost: the preceding UI interactions already leave little budget.
The fixture uses one focused paste interaction instead, retaining validation,
error focus, the exact 41-character counter, trimming, exactly one POST, success
notification and the locked interview row. The conflict and forbidden feedback
fixtures use the same paste interaction. Candidate search tests still exercise
typing. Test files run serially by default to avoid competing DOM workers on shared
runners; `--maxWorkers=N` remains available for explicit concurrency experiments.
Serial execution trades suite throughput on larger hosts for a larger CPU share
per test; a dedicated runner can explicitly choose more workers.
The timeout, retries, isolation and assertions are unchanged.

The follow-up CPU profile found substantial jsdom CSS parser/default work during
rendering (35.2% of sampled stacks; the instrumented run is diagnostic, not a
benchmark). The input-session, query, test-splitting and CSS-initialization
experiments below did not establish reliability and were removed. The original
test bodies, combined invalid-to-valid journey and standard role queries are
retained for the DOM-engine comparison.

### Offers failures are separate evidence

The original attached parallel log has four offers timeouts (including its first,
read-only test), followed by three missing-dialog errors. The feedback timeout is
in a separate file/worker and does not explain those four timeouts. The original
serial run passed all 14 offers tests. Initial controlled runs also passed all
14, but the first full run after the feedback changes reproduced an offers
rejection-reason timeout at 5,379 ms, even with one worker. That form fixture also
used per-character typing. Reason, title, salary and currency fixtures now use
focused paste interactions; whitespace validation, focus, trimming, numeric and
currency payloads, length limits and all other assertions remain intact.

The original missing-dialog pattern is consistent with unfinished asynchronous
test work interfering after a timeout; this is an inference, not a reproduced
dialog defect. Missing dialogs did not recur here, including after the reproduced
reason timeout. No production code is changed. If a
missing-dialog error occurs without preceding timeouts, investigate it separately.

## Reproduce the load

From `web/`, after `npm ci`, run:

```sh
python3 ../scripts/stress_web_tests.py --competitors 3 -- \
  npm run test:coverage -- --coverage.reportOnFailure

python3 ../scripts/stress_web_tests.py --competitors 3 -- \
  npx vitest run src/components/interviews src/lib/interviews \
  src/components/offers --coverage --coverage.reportOnFailure
```

The Linux-only helper pins the test process and three CPU-bound competitors to
the first permitted CPU and waits for the test command. It stops only its own
competitors on exit and propagates the test exit code. This models contention;
it does not claim to recreate the original Docker/Next.js workload exactly.
Run experiments sequentially, using the same competitor count and coverage mode
before and after a change. The host remains shared, so wall times vary. Local
lint/type checks and the production build ran on the other CPU during some
experiments; the initial backend test run was not affinity-pinned.

## Experiment ledger

All attempts, including failed diagnostic runs, are recorded here. Focused runs
collect coverage over the whole configured source tree, so their percentages are
not comparable with full-suite coverage. No run uses retries or a larger timeout.

| Revision / attempt | Load and selection | Result |
| --- | --- | --- |
| Baseline, focused | 1 competitor, 1 Vitest worker; interviews components/lib + offers | 45 passed; feedback 3,120 ms; offers 14 passed; 72.93 s wall time |
| Baseline, isolated feedback | 3 competitors, 1 worker, coverage, `-t 'validates feedback'` | 1 failed at 5,135 ms; 10 unselected; initially overlapped the preceding run's tail |
| Baseline, timing probe | 3 competitors, 1 worker, same selection | 1 failed at 5,214 ms; comment typing began at 4,450 ms; instrumentation removed |
| Baseline, full | 3 competitors, explicitly 2 workers, coverage | 194 passed / 1 failed (feedback 5,222 ms); offers 14 passed; 196.34 s wall time; 91.09% line coverage |
| First change, focused | 3 competitors, default 1 worker, coverage; only primary feedback fixture changed | 44 passed / 1 failed: primary feedback passed in 3,367 ms, neighboring 409 test timed out at 5,137 ms; offers 14 passed; 122.58 s wall time. This prompted applying paste to all three feedback fixtures. |
| Feedback changes, focused | 3 competitors, default 1 worker, coverage; all feedback fixtures use paste | 45 passed; primary feedback 1,948 ms, 409 case 1,430 ms; offers 14 passed; 95.33 s wall time |
| Feedback changes, full | 3 competitors, default 1 worker, coverage; offers still typed their fixtures | 194 passed / 1 failed: offers rejection reason 5,379 ms; no missing dialogs; 397.93 s wall time; 91.57% line coverage. This prompted the offers fixture changes. |
| Offers fixture smoke check | Pinned to the other CPU, no synthetic competitors, no coverage; `-t 'requires a reason\|lets a recruiter\|keeps the dialog'` | 3 passed, 11 unselected; 25.73 s Vitest duration; numeric paste and currency normalization assertions passed |
| First revision fixtures, focused | 3 competitors, default 1 worker, coverage | 45 passed; primary feedback 2,408 ms, offers rejection 1,853 ms; 115.20 s wall time |
| First revision fixtures, full | 3 competitors, default 1 worker, coverage | 195 passed; no failures or skips; 300.18 s wall time; 91.57% line coverage (baseline 91.09%, no drop) |

The original issue's three runs are historical evidence: full suite 144 passed /
8 failed; serial full suite 151 passed / 1 failed; diagnostic focused suite 21
passed. These are different selections and loads, not a measured flake probability.

## Independent QA of e74af41 (Hiếu-FE)

The first revision did **not** establish stability at heavier ambient load. Hiếu-FE
requested changes after the following attempts on Linux ARM64, two CPUs and
Node 22.22.2. Host load averages were reported as 13–16 with another workspace's
Next.js build running. The original author runs above did not capture ambient
load, so they cannot establish comparable total host pressure retrospectively.
These counts are observations from different runs, not a flake probability.

| Attempt | Revision / selection | Synthetic load | Result |
| --- | --- | --- | --- |
| QA-1 | e74af41: npm ci, lint, typecheck | none specified | Passed |
| QA-2 | e74af41: full coverage | 3 competitors, ambient 13–16 | 195 passed; 91.57% lines; 431.6 s |
| QA-3 | e74af41: focused coverage | 3 competitors, ambient 13–16 | 44 passed / 1 failed: feedback 5,533 ms |
| QA-4 | e74af41: focused coverage | 3 competitors, ambient 13–16 | 45 passed: feedback 3,868 ms; offers rejection 3,844 ms |
| QA-5 | Base 1bf5766 test files/config: focused coverage, maxWorkers=1 | 3 competitors, ambient 13–16 | 43 passed / 2 failed: feedback 5,163 ms; 409 case 5,180 ms |
| QA-6 | e74af41: focused coverage | 3 competitors, ambient 13–16 | 42 passed / 3 failed: feedback 5,274 ms; 409 case 5,266 ms; offers role refusal 5,518 ms |

The review attachment `DUTH-125-independent-qa.log` contains these runs. The
reported hiring-E2E selector failure also occurs on base `1bf5766` (CI run
45795986607) and is outside this PR's test-only diff; it is not a newly observed
production regression from this change.

## Follow-up investigation

The load helper now records permitted CPUs and start/end host load averages
(1, 5 and 15 minutes) alongside the synthetic competitor count. These are host
averages, not this test process's CPU utilization or a continuously sampled peak.
The helper also reports the command's CPU seconds and wall seconds using Linux
child-resource accounting before its competitors are reaped, excluding competitor
CPU. This includes command startup and reaped descendants, not individual test
timings. CPU/wall ratios and load averages do not by themselves establish a
per-test CPU guarantee. The original real events, focus management, DOM queries,
application timers and Vitest budget remain in use.

| Attempt | Selection / change | Competitors / ambient 1-minute load | Result |
| --- | --- | --- | --- |
| R2-1 | Three failing cases, e74af41 + timing probe, coverage | 3; observed 18–20 (start/end helper logging not yet added) | 0 passed / 3 failed: feedback 6,210 ms, 409 5,347 ms, offers refusal 5,780 ms; render 1,273 ms; 120.27 s wall time |
| R2-2 | Same cases, per-test user session with delay=null + timing probe, coverage | 3; start 17.01, end 19.10 | 1 passed / 2 failed: feedback 6,388 ms, offers refusal 5,231 ms; render 2,307 ms; 89.87 s wall time |
| R2-3 | Feedback only, same session + style/query timing probe, coverage | 3; start 20.09, end 23.69 | 1 failed at 8,421 ms; render 2,316 ms; opener query completed at 4,371 ms; measured window style calls 22 ms; 110.42 s wall time |
| R2-4 | Feedback only, same session/probe, attempted child-process CPU profiling, coverage | 3; start 13.46, end 13.61 | 1 failed at 5,725 ms; 47.53 s wall time; no CPU profile file was emitted, so this is timing evidence only |
| R2-5 | Three cases, narrowed control queries with explicit role/name/visibility checks, coverage | 3; start 9.18, end 16.33 | 1 passed / 2 failed: feedback 5,996 ms, offers refusal 6,202 ms; 409 passed at 3,727 ms; 114.78 s wall time. Query experiment subsequently removed. |
| R2-6 | Feedback only, in-process CPU profiler on query experiment, coverage | 3; start 15.88, end 17.68 | 1 failed at 9,171 ms; 75.20 s wall time; CPU profile emitted. Profiling perturbs timing; probes subsequently removed. |
| R2-7 | Three cases, standard queries restored, per-test session + real CSS environment initialization, coverage | 3; start 12.42, end 13.36 | 2 passed / 1 failed: feedback 5,307 ms; 409 2,929 ms; offers refusal 4,793 ms; 76.09 s wall time |
| R2-8 | Three cold cases, split validation assertions but keep invalid-to-valid recovery; title-text wait, coverage | 3; start 8.79, end 15.22 | 2 passed / 1 failed: feedback 4,571 ms, 409 1,876 ms; offers refusal 5,628 ms; 90.25 s wall time |
| R2-9 | Four cases including the new validation test; offers initially deep-linked, coverage | 3; start 12.84, end 26.38 | 0 passed / 4 failed: validation 5,601 ms, recovery 5,869 ms, 409 5,633 ms, offers refusal 7,963 ms; 129.40 s wall time. Concurrent sheet/list initialization experiment removed. |
| R2-10 | Focused suites, all computed CSS defaults initialized before tests; split validation and title wait, coverage | 3; start 15.98, end 36.81 | 31 passed / 15 failed; 325.52 s wall time. Failures also reached pagination, scheduling and calendar-link tests. Environment warmup and all test rewrites removed. |

### DOM engine comparison

Upstream [jsdom 31.0.0](https://github.com/jsdom/jsdom/releases/tag/v31.0.0)
replaced CSS parsing, selectors and computed styles with an integrated engine.
[jsdom 30.1.3](https://github.com/jsdom/jsdom/releases/tag/v30.1.3) is the latest
30.x patch and specifically fixes focus/interaction-test slowdowns from 30.1.2.
The comparison tried 30.1.3 as a development dependency, retaining the original
tests and setup from e74af41. Both releases require the same Node minimum (22.22.2
in the Node 22 line). The trial failed and **was reverted**, including its lockfile
changes; it did not establish that downgrading fixes this workload. The upstream
engine change and local CPU profile are investigation evidence, not proof of a
general upstream regression.

| Attempt | Selection | Competitors / ambient 1-minute load | Result |
| --- | --- | --- | --- |
| R2-11 | jsdom 30.1.3, original e74af41 test bodies/setup; three cold cases, coverage | 3; start 18.36, end 25.31 | 0 passed / 3 failed: feedback 10,999 ms, 409 5,378 ms, offers refusal 6,897 ms; 182.87 s wall time. Planned further runs stopped on this failure. |
| R2-12 | Restored jsdom 31.0.1 after npm ci, original test bodies/setup; three cold cases, coverage | 3; start 23.86, end 26.13 | 0 passed / 3 failed: feedback 5,460 ms, 409 5,123 ms, offers refusal 6,140 ms; 144.01 s wall time; command tree consumed 10.84 CPU seconds over 143.99 wall seconds (7.53%) |
| R2-13 | Restored original tests/dependencies, command launched in a separate process session; three cold cases, coverage | 3; start 16.96, end 26.06 | 0 passed / 3 failed: feedback 5,315 ms, 409 5,359 ms, offers refusal 8,351 ms; 123.56 s wall time; 10.93 command CPU seconds / 123.53 wall seconds (8.85%). Session-launch experiment not retained. |

A measurement setup attempt using unavailable `/usr/bin/time` executed no tests.
The helper's Python child-resource accounting replaced that external-tool need.

`npm audit` on that trial reported four Moderate findings in the existing shadcn /
ts-morph / minimatch dependency chain, with no High or Critical findings. No
production dependency version changed in the trial, and the entire dependency
change was removed. The original dependencies were reinstalled with `npm ci`.

The separate backend check passed: 297 tests, 28 skipped, 90.57% coverage, taking
809.41 seconds on this shared runner. Lint, type checking, production build and
Ruff checks passed during the investigation. These do not override the remaining
web timeouts. No new QA approval is claimed.

### Capacity calibration and required decision

With the same three competitors, the pure-CPU command below consumed 0.26 CPU
seconds over 5.25 wall seconds (4.90% of one CPU), with host load averages 23.19
at start and 22.85 at end. This is command-wide accounting, not an inferred
per-test wait percentage:

```sh
python3 ../scripts/stress_web_tests.py --competitors 3 -- \
  python3 -c 'sum(i * i for i in range(3000000))'
```

A second calibration launched that CPU command in a separate process session:
0.29 CPU seconds / 2.92 wall seconds (10.06%), ambient 24.63 to 23.86. This single
sample does not distinguish a scheduling benefit from ambient variation; the
unchanged test cases were also checked through that launch path. No session or
scheduler policy changes are retained in the helper.

A fixed five-second behavior budget needs a bounded execution allocation to be
meaningfully compared. A reserved QA window (one CPU for the test command plus its
three controlled competitors) was proposed but could not be arranged.

### Acceptance decision

The project owner decided to skip the CPU-contention acceptance comparison. The
loaded timeouts recorded above (QA-3, QA-5, QA-6, R2-1 to R2-13) are accepted as a
known risk of running on the shared two-CPU runner, not as a passing result. Timeouts,
retries, isolation and assertions stay unchanged. Independent QA of the final head
covered the diff, the ledger and the helper, and ran lint, typecheck and the full web
suite without synthetic load. If these tests time out in CI, first check
host load with the helper before changing tests.
