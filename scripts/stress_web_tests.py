"""Run a web test command with reproducible Linux CPU contention.

Invoke from web/, for example:
    python ../scripts/stress_web_tests.py --competitors 3 -- npm run test:coverage
"""

import argparse
import os
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competitors", type=int, default=3)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.competitors < 0 or not command:
        parser.error("supply a command and a non-negative competitor count")

    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    workers = []
    started = time.monotonic()
    try:
        for _ in range(args.competitors):
            workers.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
        print(f"LOAD cpu={cpu}, competitors={args.competitors}, command={command}", flush=True)
        return subprocess.run(command, check=False).returncode
    finally:
        for worker in workers:
            worker.terminate()
        for worker in workers:
            worker.wait()
        print(f"LOAD elapsed={time.monotonic() - started:.2f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
