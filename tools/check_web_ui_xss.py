#!/usr/bin/env python3
"""Guards tools/web_ui/index.html against a stored-XSS regression.

Today every daemon-sourced field (branch name, CI workflow name, VS Code
error text, weather location...) is rendered via .textContent, which can't
execute markup even if a future upstream source lets attacker-controlled
text into one of those fields (e.g. a malicious git branch name). This
script fails the build if a NEW `.innerHTML =` assignment shows up in the
page that isn't on the explicit allowlist below -- forcing a deliberate,
reviewed decision instead of a silent regression.

Usage: python tools/check_web_ui_xss.py
Exit code 0 if clean, 1 if an unreviewed innerHTML assignment is found.
"""
import re
import sys
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "web_ui" / "index.html"

# Each entry: the element id assigned to, and why it's safe today. Adding a
# new one here is a real security decision -- don't just paste an id to
# silence the check.
ALLOWED_INNERHTML = {
    # Built from a hardcoded <span> template plus WiFi.localIP().toString()
    # (numeric dotted-quad, never free text) -- never a daemon-controlled
    # string. If this field ever starts including anything the daemon or an
    # upstream API supplies verbatim, switch it to textContent/DOM nodes.
    "conn-line",
}

INNERHTML_RE = re.compile(r"""document\.getElementById\((['"])([\w-]+)\1\)\.innerHTML\s*=""")


def main() -> int:
    html = HTML_PATH.read_text(encoding="utf-8")
    found = {m.group(2) for m in INNERHTML_RE.finditer(html)}
    unreviewed = found - ALLOWED_INNERHTML
    stale = ALLOWED_INNERHTML - found
    ok = True
    if unreviewed:
        ok = False
        print("FAIL: unreviewed innerHTML assignment(s) in tools/web_ui/index.html:")
        for eid in sorted(unreviewed):
            print(f"  #{eid}")
        print("If this is intentional and safe (no attacker/daemon-controlled string reaches")
        print("it unsanitized), add it to ALLOWED_INNERHTML in this script with a comment")
        print("explaining why. Otherwise use .textContent or build DOM nodes instead.")
    if stale:
        print("NOTE: these allowlisted ids no longer use innerHTML -- remove from the allowlist:")
        for eid in sorted(stale):
            print(f"  #{eid}")
    if ok:
        print(f"OK: innerHTML usage in index.html matches the reviewed allowlist ({len(found)} found)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
