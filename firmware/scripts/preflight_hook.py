# PlatformIO extra_script (pre:) -- wires tools/ checks into the build itself.
#
#  * After firmware.bin is linked: print the resource report summary
#    (tools/resource_report.py --quiet). Informational here -- a budget
#    failure is printed but doesn't fail a plain `pio run`, so iterating on a
#    build that's temporarily over a gate still works.
#  * Before `-t upload`: run tools/preflight.py --no-build (unit tests,
#    consistency/auth/XSS guards, resource gates). Any failure aborts the
#    upload -- nothing reaches the device without passing the gates.
#    Escape hatch for an emergency flash: CLAWDMETER_SKIP_PREFLIGHT=1.
#
# Runs under PlatformIO's own python ($PYTHONEXE); every script it calls is
# stdlib-only (daemon tests skip themselves when httpx is absent).
import os
import subprocess

Import("env")  # noqa: F821  (SCons global)

ROOT = os.path.abspath(os.path.join(env.subst("$PROJECT_DIR"), ".."))  # noqa: F821
TOOLS = os.path.join(ROOT, "tools")
PY = env.subst("$PYTHONEXE")  # noqa: F821
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")  # gotcha #10


def _run(args):
    return subprocess.call([PY] + args, cwd=ROOT, env=CHILD_ENV)


def resource_summary(source, target, env):
    _run([os.path.join(TOOLS, "resource_report.py"), "--quiet"])


def preflight_gate(source, target, env):
    if os.environ.get("CLAWDMETER_SKIP_PREFLIGHT") == "1":
        print("*** CLAWDMETER_SKIP_PREFLIGHT=1 -- skipping pre-flash gates ***")
        return
    print("\n=== Pre-flash gates (tools/preflight.py --no-build) ===")
    if _run([os.path.join(TOOLS, "preflight.py"), "--no-build"]) != 0:
        print("\n*** Pre-flash gates FAILED -- upload aborted. Fix the failures above, "
              "or set CLAWDMETER_SKIP_PREFLIGHT=1 to override. ***")
        env.Exit(1)


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", resource_summary)  # noqa: F821
env.AddPreAction("upload", preflight_gate)  # noqa: F821
