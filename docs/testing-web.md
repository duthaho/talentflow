# Web component tests under CPU contention

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
| Final fixtures, focused | 3 competitors, default 1 worker, coverage | 45 passed; primary feedback 2,408 ms, offers rejection 1,853 ms; 115.20 s wall time |
| Final fixtures, full | 3 competitors, default 1 worker, coverage | 195 passed; no failures or skips; 300.18 s wall time; 91.57% line coverage (baseline 91.09%, no drop) |

The original issue's three runs are historical evidence: full suite 144 passed /
8 failed; serial full suite 151 passed / 1 failed; diagnostic focused suite 21
passed. These are different selections and loads, not a measured flake probability.
