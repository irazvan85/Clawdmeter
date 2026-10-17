#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write|MultiEdit): run the cheap, file-specific guard
for whatever was just edited, so drift is caught at edit time instead of at
flash time.

  tools/web_ui/index.html     -> regenerate firmware/src/web_ui.h (node
                                 tools/build_web_ui.js) -- the header is
                                 generated, and forgetting this ships a stale
                                 page; then check_web_ui_xss.py
  firmware/src/web_server.cpp -> check_auth_gated_routes.py
  ui.h / ui.cpp / device_config.cpp / index.html / claudepix_data/*.json
                              -> check_consistency.py (screen tables, splash index)

A failing guard exits 2 so its output is fed back to Claude. Never blocks on
its own errors (missing node, etc.) -- those just print a note.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def rel(p: str) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    ti = data.get("tool_input") or {}
    path = rel(ti.get("file_path") or ti.get("path") or "")
    if not path:
        return 0

    py = sys.executable
    failures, notes = [], []

    if path == "tools/web_ui/index.html":
        node = shutil.which("node")
        if node:
            rc, out = run([node, "tools/build_web_ui.js"])
            (notes if rc == 0 else failures).append(f"build_web_ui.js: {out}")
        else:
            notes.append("node not found -- run `node tools/build_web_ui.js` manually to refresh web_ui.h")
        rc, out = run([py, "tools/check_web_ui_xss.py"])
        if rc:
            failures.append(out)

    if path == "firmware/src/web_server.cpp":
        rc, out = run([py, "tools/check_auth_gated_routes.py"])
        if rc:
            failures.append(out)

    if path in ("firmware/src/ui.h", "firmware/src/ui.cpp", "firmware/src/device_config.cpp",
                "tools/web_ui/index.html") or path.startswith("tools/claudepix_data/"):
        rc, out = run([py, "tools/check_consistency.py"])
        if rc:
            failures.append(out)

    if failures:
        print(f"Guard failed after editing {path}:\n\n" + "\n\n".join(failures), file=sys.stderr)
        return 2
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": "\n".join(notes)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
