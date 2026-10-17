#!/usr/bin/env python3
"""Pre-flash resource report + budget gate for the firmware build.

Superset of check_static_mem.py (kept for its existing callers): reads the
built ELF/BIN and reports every budget that can sink this board, then
compares against a committed baseline (tools/resource_baseline.json).

  app partition  firmware.bin vs the factory app slot in partitions_app.csv
  static DRAM    .dram0.data + .dram0.bss (same figure as `pio run`'s "RAM:")
  IRAM           .iram0.vectors + .iram0.text vs the 128 KB IRAM region
  flash code     .flash.text / .flash.rodata (informational)
  top symbols    largest DRAM (.data/.bss) and flash symbols, via nm --size-sort,
                 so a regression points straight at the global that caused it

Writes Markdown + JSON next to the ELF (resource_report.{md,json}) and
prints the Markdown. Exit 1 if any gate fails:

  * app partition > 90% full
  * IRAM > 95% full (IRAM overflow is a link error, but near-full means the
    next IRAM_ATTR addition breaks the build)
  * any tracked metric grew more than its allowed delta past the baseline
    (static DRAM +15% -- the same threshold check_static_mem.py uses)

Remember (CLAUDE.md gotcha #14): passing this does NOT mean the runtime heap
is fine -- static RAM sat at ~20% the whole time that bug crash-looped the
device. tools/perf_check.py measures the runtime side on a real device.

Usage:
    python tools/resource_report.py                    # report + gate
    python tools/resource_report.py --update-baseline  # accept current sizes
    python tools/resource_report.py --top 20           # longer symbol lists
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = "ideaspark_114_st7789"
BUILD = ROOT / "firmware" / ".pio" / "build" / ENV
ELF = BUILD / "firmware.elf"
BIN = BUILD / "firmware.bin"
PARTITIONS = ROOT / "firmware" / "partitions_app.csv"
BASELINE = Path(__file__).resolve().parent / "resource_baseline.json"
TOOLCHAIN = Path.home() / ".platformio" / "packages" / "toolchain-xtensa-esp-elf" / "bin"

DRAM_TOTAL = 327680        # same total pio run reports for "RAM:"
IRAM_TOTAL = 131072        # ESP32 IRAM0 region available to the app

APP_PART_MAX_PCT = 90.0
IRAM_MAX_PCT = 95.0
# metric -> allowed relative growth over baseline before failing
GROWTH_GATES = {"static_dram": 0.15, "iram": 0.10, "app_bin": 0.20}


def tool(name: str) -> str:
    hits = sorted(TOOLCHAIN.glob(f"xtensa-esp32-elf-{name}*"))
    if not hits:
        sys.exit(f"xtensa-esp32-elf-{name} not found under {TOOLCHAIN} -- run `pio run -d firmware` once first")
    return str(hits[0])


def app_partition_size() -> int:
    for line in PARTITIONS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 5 and cols[1] == "app":
            return int(cols[4], 0)
    sys.exit(f"no app partition in {PARTITIONS}")


def sections(elf: Path) -> dict[str, int]:
    out = subprocess.run([tool("size"), "-A", str(elf)], capture_output=True, text=True, check=True).stdout
    sec = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(".") and parts[1].isdigit():
            sec[parts[0]] = int(parts[1])
    return sec


def top_symbols(elf: Path, n: int) -> dict[str, list[tuple[int, str]]]:
    out = subprocess.run([tool("nm"), "-S", "-C", "--size-sort", "-r", str(elf)],
                         capture_output=True, text=True, check=True).stdout
    dram, flash = [], []
    for line in out.splitlines():
        m = re.match(r"([0-9a-f]+)\s+([0-9a-f]+)\s+(\w)\s+(.*)", line)
        if not m:
            continue
        addr, size, kind, name = int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4)
        if 0x3FFAE000 <= addr < 0x40000000 and kind in "bBdD":   # DRAM data/bss
            dram.append((size, name))
        elif 0x3F400000 <= addr < 0x3F800000 or 0x400D0000 <= addr < 0x40400000:  # flash rodata/text
            flash.append((size, name))
    return {"dram": dram[:n], "flash": flash[:n]}


def measure(top_n: int) -> dict:
    for p in (ELF, BIN):
        if not p.exists():
            sys.exit(f"{p} not found -- run `pio run -d firmware` first")
    sec = sections(ELF)
    m = {
        "static_dram": sec.get(".dram0.data", 0) + sec.get(".dram0.bss", 0),
        "dram_data": sec.get(".dram0.data", 0),
        "dram_bss": sec.get(".dram0.bss", 0),
        "iram": sec.get(".iram0.vectors", 0) + sec.get(".iram0.text", 0),
        "flash_text": sec.get(".flash.text", 0),
        "flash_rodata": sec.get(".flash.rodata", 0),
        "app_bin": BIN.stat().st_size,
        "app_partition": app_partition_size(),
    }
    m["top"] = top_symbols(ELF, top_n)
    return m


def pct(a: int, b: int) -> float:
    return 100.0 * a / b if b else 0.0


def evaluate(m: dict, base: dict | None) -> list[str]:
    fails = []
    app_pct = pct(m["app_bin"], m["app_partition"])
    if app_pct > APP_PART_MAX_PCT:
        fails.append(f"app binary uses {app_pct:.1f}% of the app partition (limit {APP_PART_MAX_PCT}%)")
    iram_pct = pct(m["iram"], IRAM_TOTAL)
    if iram_pct > IRAM_MAX_PCT:
        fails.append(f"IRAM {iram_pct:.1f}% full (limit {IRAM_MAX_PCT}%)")
    if base:
        for k, allowed in GROWTH_GATES.items():
            if k in base and base[k] and m[k] > base[k] * (1 + allowed):
                fails.append(f"{k} grew {base[k]} -> {m[k]} (+{pct(m[k] - base[k], base[k]):.1f}%, "
                             f"allowed +{allowed:.0%}); if intended, re-run with --update-baseline")
    return fails


def fmt_delta(cur: int, base: dict | None, key: str) -> str:
    if not base or key not in base:
        return "-"
    d = cur - base[key]
    return f"{d:+,}" if d else "0"


def render(m: dict, base: dict | None, fails: list[str]) -> str:
    rows = [
        ("App partition", m["app_bin"], m["app_partition"], "app_bin"),
        ("Static DRAM (.data+.bss)", m["static_dram"], DRAM_TOTAL, "static_dram"),
        ("IRAM", m["iram"], IRAM_TOTAL, "iram"),
        ("Flash .text", m["flash_text"], None, "flash_text"),
        ("Flash .rodata", m["flash_rodata"], None, "flash_rodata"),
    ]
    out = ["# Firmware resource report", "",
           "| Budget | Used (bytes) | Of | % | Delta vs baseline |", "|---|---:|---:|---:|---:|"]
    for name, used, total, key in rows:
        out.append(f"| {name} | {used:,} | {f'{total:,}' if total else '-'} | "
                   f"{f'{pct(used, total):.1f}%' if total else '-'} | {fmt_delta(used, base, key)} |")
    out += ["", f"DRAM split: .data {m['dram_data']:,} / .bss {m['dram_bss']:,}. "
            "Static only; runtime heap is measured by `tools/perf_check.py`.", ""]
    for label, key in (("Largest DRAM symbols", "dram"), ("Largest flash symbols", "flash")):
        out += [f"## {label}", "", "| Bytes | Symbol |", "|---:|---|"]
        out += [f"| {s:,} | `{n[:90]}` |" for s, n in m["top"][key]]
        out.append("")
    out.append("## Result")
    out.append("")
    out += [f"- FAIL: {f}" for f in fails] if fails else ["- PASS: all resource gates within budget"]
    if not base:
        out.append("- (no baseline yet; run with `--update-baseline` to create one)")
    return "\n".join(out) + "\n"


def main() -> int:
    # Windows consoles default to cp1252 (CLAUDE.md gotcha #10) -- don't let
    # the report's non-ASCII characters crash the gate.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--quiet", action="store_true", help="print only the summary table and result")
    a = ap.parse_args()

    m = measure(a.top)
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    fails = [] if a.update_baseline else evaluate(m, base)
    md = render(m, base, fails)

    (BUILD / "resource_report.md").write_text(md, encoding="utf-8")
    (BUILD / "resource_report.json").write_text(json.dumps({**m, "fails": fails}, indent=2), encoding="utf-8")
    if a.quiet:
        lines = md.splitlines()
        cut = next(i for i, l in enumerate(lines) if l.startswith("## Largest"))
        res = lines.index("## Result")
        print("\n".join(lines[:cut] + lines[res:]))
    else:
        print(md)
    print(f"(full report: {BUILD / 'resource_report.md'})")

    if a.update_baseline:
        keep = {k: m[k] for k in ("static_dram", "iram", "app_bin", "flash_text", "flash_rodata")}
        BASELINE.write_text(json.dumps(keep, indent=2) + "\n")
        print(f"Baseline written: {BASELINE}")
        return 0
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
