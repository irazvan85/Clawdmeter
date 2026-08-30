#!/usr/bin/env python3
"""Merge Clawdmeter activity hooks into ~/.claude/settings.json.

Adds a `command` hook that runs daemon/hook.py for the events the Clawdmeter
Clock/Splash activity signal needs. Existing hooks and every other settings key
are preserved; running this twice is a no-op.

    python daemon/install_hooks.py            # install / update
    python daemon/install_hooks.py --remove   # take them back out

NOTE: the settings.json `hooks` schema is confirmed against Claude Code as of
2026-02; if a future version changes it, re-check `claude` docs.
"""
import json
import shlex
import sys
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = Path(__file__).resolve().parent / "hook.py"
EVENTS = ("UserPromptSubmit", "Stop", "SubagentStop", "Notification",
          "SessionStart", "SessionEnd")
# Our hook command always ends in ".../daemon/hook.py" — enough of a marker to
# find and replace it without touching anyone else's hooks.
MARKER = "hook.py"


def _command() -> str:
    py = shlex.quote(sys.executable)
    return f'{py} {shlex.quote(str(HOOK_SCRIPT))}'


def _is_ours(hook: object) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def load() -> dict:
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(d: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")


def install(remove: bool) -> None:
    if not HOOK_SCRIPT.exists():
        sys.exit(f"hook script not found: {HOOK_SCRIPT}")

    cfg = load()
    hooks = cfg.setdefault("hooks", {})
    entry = {"type": "command", "command": _command()}

    for ev in EVENTS:
        groups = [g for g in hooks.get(ev, []) if isinstance(g, dict)]
        # drop any previous Clawdmeter hook from every group
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h)]
        groups = [g for g in groups if g.get("hooks")]
        if not remove:
            groups.append({"hooks": [entry]})
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)

    if not hooks:
        cfg.pop("hooks", None)

    save(cfg)
    print(("Removed" if remove else "Installed"),
          "Clawdmeter activity hooks in", SETTINGS)
    if not remove:
        print("Start a new Claude Code session for them to take effect.")


if __name__ == "__main__":
    install(remove="--remove" in sys.argv)
