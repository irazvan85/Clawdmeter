#!/usr/bin/env python3
"""Claude Code hook -> one activity line the usage daemon tails.

Registered by install_hooks.py for UserPromptSubmit / Stop / SubagentStop /
Notification / SessionStart / SessionEnd. Claude Code pipes a JSON object on
stdin (hook_event_name, session_id, cwd, transcript_path, ...). We append

    <epoch>\\t<event>\\t<session_id>\\t<cwd>

to ~/.config/claude-usage-monitor/activity.log and exit 0 with no stdout so we
never interfere with the session.
"""
import json
import os
import sys
import time
from pathlib import Path

LOG = Path.home() / ".config" / "claude-usage-monitor" / "activity.log"
MAX_BYTES = 64_000


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, ValueError):
        data = {}

    event = data.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "?")
    sid = str(data.get("session_id") or "?")[:12]
    cwd = data.get("cwd") or os.getcwd()

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\t{event}\t{sid}\t{cwd}\n")
        if LOG.stat().st_size > MAX_BYTES:
            tail = LOG.read_text(encoding="utf-8").splitlines()[-200:]
            LOG.write_text("\n".join(tail) + "\n", encoding="utf-8")
    except OSError:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
