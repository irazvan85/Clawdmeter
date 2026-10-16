#!/usr/bin/env python3
"""PreToolUse hook (Bash|Read|Glob|Grep): suggest `graphify query` before raw
code exploration -- at most once per session, and only when the graph is
actually current.

Replaces two inline `python3 -c` one-liners that never ran on this machine
(no `python3` on Windows; `|| true` swallowed the failure) and that, had they
run, would have said "MANDATORY" while pointing at a weeks-old graph. A stale
graph is worse than none, so this stays silent unless graph.json is newer
than the last commit.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
GRAPH = ROOT / "graphify-out" / "graph.json"
SEARCH_WORDS = ("grep", "rg ", "find ", "fd ", "ack ", "ag ")
CODE_EXTS = (".py", ".js", ".c", ".h", ".cpp", ".hpp", ".ino", ".sh", ".ps1")


def graph_is_current() -> bool:
    if not GRAPH.exists():
        return False
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return GRAPH.stat().st_mtime >= int(out or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        cmd = ti.get("command", "")
        if not any(w in cmd for w in SEARCH_WORDS):
            return 0
    else:
        target = " ".join(str(ti.get(k) or "") for k in ("file_path", "pattern", "path")).lower()
        if "graphify-out" in target or not any(e in target for e in CODE_EXTS):
            return 0

    marker = Path(tempfile.gettempdir()) / f"clawdmeter-graphify-nudge-{data.get('session_id', 'x')}"
    if marker.exists() or not graph_is_current():
        return 0
    marker.touch()
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": ("graphify-out/graph.json is current. For orientation questions, "
                              "`graphify query \"<question>\"` / `graphify explain \"<concept>\"` "
                              "return a scoped subgraph cheaper than raw grep/read. "
                              "(Shown once per session.)"),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
