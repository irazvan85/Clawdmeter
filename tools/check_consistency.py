#!/usr/bin/env python3
"""Cross-file consistency checks for tables this project keeps in sync by hand.

Each check below guards a "keep X in sync with Y" comment somewhere in the
codebase -- the kind of invariant that compiles fine when broken and only
shows up as a wrong screen, a mis-labeled checkbox, or a stale web page on
the device.

  screen-enum       ui.h's screen_t enum vs SCREEN_COUNT (13)
  cycle-order       ui.cpp CYCLE_ORDER[] == device_config.cpp CFG_SCREEN_ORDER[]
                    (bit i of the visibility mask means CYCLE_ORDER[i])
  required-bits     device_config.cpp CLOCK_BIT/CONN_BIT point at Clock/Connectivity
  web-screen-names  index.html SCREEN_NAMES[] has one entry per screen_t value
  web-cfg-screens   index.html CFG_SCREENS[] bits/labels match CFG_SCREEN_ORDER[]
  web-ui-fresh      firmware/src/web_ui.h decompresses to exactly tools/web_ui/index.html
                    (i.e. someone ran tools/build_web_ui.js after editing the page)
  splash-index      every tools/claudepix_data/*.json is listed in _index.json
                    (convert_to_c.js silently drops unindexed animations)

Stdlib only. Usage: python tools/check_consistency.py [--only NAME ...]
Exit code 0 if all selected checks pass, 1 otherwise.
"""
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware" / "src"
WEB = ROOT / "tools" / "web_ui" / "index.html"

# screen_t enumerator -> label the web UI uses for it. Kept here (not parsed)
# because the web UI is the only place labels exist; this table is what the
# check compares *against*, so a rename on either side is caught.
LABELS = {
    "SCREEN_SPLASH": "Splash", "SCREEN_CLOCK": "Clock", "SCREEN_SENSOR": "Sensor",
    "SCREEN_SENSOR_GRAPH": "Sensor Trend", "SCREEN_USAGE": "Usage",
    "SCREEN_COPILOT": "Copilot", "SCREEN_SYSINFO": "SysInfo", "SCREEN_VSCODE": "VS Code",
    "SCREEN_BLUETOOTH": "Connectivity", "SCREEN_CI": "Checks", "SCREEN_TODAY": "Today",
    "SCREEN_AURORA": "Aurora",
    "SCREEN_CODEX": "Codex",
}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def parse_screen_enum() -> list[str]:
    s = _strip_comments(_read(SRC / "ui.h"))
    m = (re.search(r"enum\s+screen_t\s*\{(.*?)\}\s*;", s, re.S)
         or re.search(r"typedef\s+enum\s*\{(.*?)\}\s*screen_t\s*;", s, re.S))
    if not m:
        raise AssertionError("screen_t enum not found in ui.h")
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


def parse_c_array(path: Path, name: str) -> list[str]:
    s = _strip_comments(_read(path))
    m = re.search(rf"{name}\s*\[\]\s*=\s*\{{(.*?)\}};", s, re.S)
    if not m:
        raise AssertionError(f"{name}[] not found in {path.name}")
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


def parse_js_array(text: str, name: str) -> str:
    m = re.search(rf"const\s+{name}\s*=\s*\[(.*?)\];", text, re.S)
    if not m:
        raise AssertionError(f"const {name} = [...] not found in index.html")
    return m.group(1)


# ---------------------------------------------------------------- checks

def check_screen_enum() -> list[str]:
    e = parse_screen_enum()
    errs = []
    if e[-1] != "SCREEN_COUNT":
        errs.append(f"screen_t must end with SCREEN_COUNT, ends with {e[-1]}")
    unknown = [x for x in e[:-1] if x not in LABELS]
    if unknown:
        errs.append(f"screen_t has values with no label in check_consistency.LABELS: {unknown}")
    return errs


def check_cycle_order() -> list[str]:
    a = parse_c_array(SRC / "ui.cpp", "CYCLE_ORDER")
    b = parse_c_array(SRC / "device_config.cpp", "CFG_SCREEN_ORDER")
    errs = []
    if a != b:
        errs.append(f"CYCLE_ORDER {a}\n   != CFG_SCREEN_ORDER {b}")
    enum = parse_screen_enum()[:-1]
    missing = [x for x in enum if x not in a and x != "SCREEN_SPLASH"]
    if missing:
        errs.append(f"screens missing from CYCLE_ORDER (unreachable by button): {missing}")
    if len(a) > 16:
        errs.append(f"CYCLE_ORDER has {len(a)} entries; visibility mask is uint16_t")
    return errs


def check_required_bits() -> list[str]:
    order = parse_c_array(SRC / "device_config.cpp", "CFG_SCREEN_ORDER")
    s = _read(SRC / "device_config.cpp")
    errs = []
    for macro, want in (("CLOCK_BIT", "SCREEN_CLOCK"), ("CONN_BIT", "SCREEN_BLUETOOTH")):
        m = re.search(rf"#define\s+{macro}\s+\(1u\s*<<\s*(\d+)\)", s)
        if not m:
            errs.append(f"#define {macro} (1u << N) not found")
            continue
        i = int(m.group(1))
        if i >= len(order) or order[i] != want:
            errs.append(f"{macro} is bit {i} = {order[i] if i < len(order) else '?'}, expected {want}")
    return errs


def check_web_screen_names() -> list[str]:
    names = re.findall(r"'([^']*)'", parse_js_array(_read(WEB), "SCREEN_NAMES"))
    want = [LABELS[x] for x in parse_screen_enum()[:-1]]
    if names != want:
        return [f"SCREEN_NAMES {names}\n   != screen_t order {want}"]
    return []


def check_web_cfg_screens() -> list[str]:
    body = parse_js_array(_read(WEB), "CFG_SCREENS")
    entries = [(int(b), l) for b, l in re.findall(r"bit:\s*(\d+)\s*,\s*label:\s*'([^']*)'", body)]
    order = parse_c_array(SRC / "device_config.cpp", "CFG_SCREEN_ORDER")
    errs = []
    for bit, label in entries:
        if bit >= len(order):
            errs.append(f"CFG_SCREENS bit {bit} ('{label}') out of range ({len(order)} screens)")
        elif LABELS[order[bit]] != label:
            errs.append(f"CFG_SCREENS bit {bit} labeled '{label}' but CFG_SCREEN_ORDER[{bit}] is {order[bit]} ('{LABELS[order[bit]]}')")
    # Every non-forced bit should be offered, or the user can't toggle it.
    offered = {b for b, _ in entries}
    forced = {order.index("SCREEN_CLOCK"), order.index("SCREEN_BLUETOOTH")}
    missing = [f"{i}:{LABELS[order[i]]}" for i in range(len(order)) if i not in offered | forced]
    if missing:
        errs.append(f"CFG_SCREENS doesn't offer bits {missing}")
    return errs


def check_web_ui_fresh() -> list[str]:
    h = _read(SRC / "web_ui.h")
    m = re.search(r"INDEX_HTML_GZ\[\]\s*=\s*\{(.*?)\};", h, re.S)
    if not m:
        return ["INDEX_HTML_GZ[] not found in web_ui.h"]
    data = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))
    lm = re.search(r"INDEX_HTML_GZ_LEN\s*=\s*(\d+)", h)
    errs = []
    if lm and int(lm.group(1)) != len(data):
        errs.append(f"INDEX_HTML_GZ_LEN={lm.group(1)} but array has {len(data)} bytes")
    try:
        html = gzip.decompress(data)
    except OSError as e:
        return errs + [f"web_ui.h payload isn't valid gzip: {e}"]
    # Compare line-ending-insensitively: with core.autocrlf=true the page is
    # checked out CRLF on Windows and LF elsewhere, and older headers were
    # generated from whichever was on disk (build_web_ui.js now normalizes).
    if html.replace(b"\r\n", b"\n") != WEB.read_bytes().replace(b"\r\n", b"\n"):
        errs.append("web_ui.h is stale -- run `node tools/build_web_ui.js` after editing tools/web_ui/index.html")
    return errs


def check_splash_index() -> list[str]:
    d = ROOT / "tools" / "claudepix_data"
    idx = json.loads(_read(d / "_index.json"))
    indexed = {Path(e["filename"]).stem for e in idx}
    files = {p.stem for p in d.glob("*.json") if p.name != "_index.json"}
    errs = []
    if files - indexed:
        errs.append(f"animations not in _index.json (convert_to_c.js will drop them): {sorted(files - indexed)}")
    if indexed - files:
        errs.append(f"_index.json lists animations with no .json file: {sorted(indexed - files)}")
    return errs


CHECKS = {
    "screen-enum": check_screen_enum,
    "cycle-order": check_cycle_order,
    "required-bits": check_required_bits,
    "web-screen-names": check_web_screen_names,
    "web-cfg-screens": check_web_cfg_screens,
    "web-ui-fresh": check_web_ui_fresh,
    "splash-index": check_splash_index,
}


def run(names: list[str]) -> int:
    failed = 0
    for name in names:
        try:
            errs = CHECKS[name]()
        except AssertionError as e:
            errs = [f"parse error: {e}"]
        if errs:
            failed += 1
            print(f"FAIL {name}")
            for e in errs:
                print(f"   {e}")
        else:
            print(f"ok   {name}")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    names = list(CHECKS)
    if "--only" in argv:
        names = argv[argv.index("--only") + 1:]
        bad = [n for n in names if n not in CHECKS]
        if bad:
            print(f"unknown check(s): {bad}; available: {list(CHECKS)}")
            return 2
    return run(names)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
