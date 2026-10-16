#!/usr/bin/env python3
"""One command for "is this safe to flash?" -- runs every host-side gate in order.

Stages (each one's exit code is collected; nothing stops early unless --fail-fast):

  tests      python -m unittest over tools/tests (payload contract, consistency
             checker mutations, resource/perf gate logic, daemon helpers --
             daemon tests skip if httpx isn't installed in this interpreter)
  static     check_consistency.py, check_auth_gated_routes.py, check_web_ui_xss.py
  build      pio run -d firmware            (skipped with --no-build)
  resources  resource_report.py --quiet     (needs a build; app-partition / DRAM /
                                             IRAM budgets + baseline deltas)

Also runs automatically before every `pio run -t upload` via
firmware/scripts/preflight_hook.py (with --no-build, since PlatformIO has
just built). Set CLAWDMETER_SKIP_PREFLIGHT=1 to bypass that hook for one
emergency flash.

The on-device side (runtime heap, LVGL frame time, HTTP latency) is
tools/perf_check.py -- run it after flashing.

Usage:
    python tools/preflight.py                 # full run incl. build
    python tools/preflight.py --no-build      # gates only, against the existing build
    python tools/preflight.py --only static tests
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
PIO = Path.home() / ".platformio" / "penv" / "Scripts" / "pio.exe"
if not PIO.exists():
    PIO = Path.home() / ".platformio" / "penv" / "bin" / "pio"

STAGES = ("tests", "static", "build", "resources")


def commands(py: str) -> dict[str, list[tuple[str, list[str]]]]:
    return {
        "tests": [("unit tests", [py, "-m", "unittest", "discover", "-s", str(TOOLS / "tests"),
                                  "-t", str(TOOLS / "tests")])],
        "static": [
            ("consistency", [py, str(TOOLS / "check_consistency.py")]),
            ("auth-gated routes", [py, str(TOOLS / "check_auth_gated_routes.py")]),
            ("web UI XSS guard", [py, str(TOOLS / "check_web_ui_xss.py")]),
        ],
        "build": [("pio run", [str(PIO), "run", "-d", str(ROOT / "firmware")])],
        "resources": [("resource report", [py, str(TOOLS / "resource_report.py"), "--quiet"])],
    }


def run_step(label: str, cmd: list[str], verbose: bool) -> tuple[bool, float, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")   # gotcha #10
    t = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    dt = time.time() - t
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0
    if verbose or not ok:
        print(f"\n----- {label} ({'ok' if ok else f'exit {p.returncode}'}) -----")
        print(out.rstrip())
    return ok, dt, out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="Pre-flash gates for the Clawdmeter firmware")
    ap.add_argument("--no-build", action="store_true", help="skip `pio run` (use the existing build)")
    ap.add_argument("--only", nargs="+", choices=STAGES, help="run just these stages")
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="print output of passing steps too")
    a = ap.parse_args()

    stages = list(a.only or STAGES)
    if a.no_build and "build" in stages:
        stages.remove("build")
    cmds = commands(sys.executable)

    results = []
    for stage in stages:
        for label, cmd in cmds[stage]:
            print(f"[{stage}] {label} ...", flush=True)
            ok, dt, out = run_step(label, cmd, a.verbose or stage == "resources")
            results.append((stage, label, ok, dt))
            if not ok and a.fail_fast:
                break
        else:
            continue
        break

    print("\n===== preflight summary =====")
    for stage, label, ok, dt in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {stage:<9} {label:<20} {dt:5.1f}s")
    failed = [r for r in results if not r[2]]
    print(f"\n{'FAILED' if failed else 'OK'}: {len(results) - len(failed)}/{len(results)} steps passed"
          + ("" if failed else " -- safe to flash; run tools/perf_check.py after."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
