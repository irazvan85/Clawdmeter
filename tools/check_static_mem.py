#!/usr/bin/env python3
"""Static-RAM regression check for the firmware build.

Run after `pio run`, before flashing. Parses `.dram0.data`/`.dram0.bss`
section sizes straight out of the built ELF via `xtensa-esp32-elf-size -A`
(clean numeric per-section output, no screen-scraping `pio run`'s
human-readable report, which also sidesteps the Windows console-codepage
issue documented as CLAUDE.md gotcha #10 for this specific check) and fails
if static RAM usage grew past a committed baseline
(tools/static_mem_baseline.json) by more than a relative threshold.

NOTE: `size`'s generic Berkeley text/data/bss mode (`-B`) does NOT work on
this project's ESP32/Xtensa linker script -- it lumps flash-resident
read-only data in with "data", producing a nonsense total (measured: 156%
of DRAM on a device that boots fine at 18%). `.dram0.data` + `.dram0.bss`
from `-A`'s per-section output is what actually lands in DRAM at runtime --
verified to exactly match `pio run`'s own "RAM: used N bytes" figure.

IMPORTANT LIMITATION: this is a *static*-bloat regression guard only. It
tracks memory reserved at link time. It does NOT catch runtime heap
fragmentation or exhaustion. CLAUDE.md gotcha #14 documents an entire
crash-looping saga where static RAM usage sat at ~20.5% the whole time the
device was crashing -- the real problem was how much *heap* was left once
WiFi's driver claimed its share, not anything this script would ever see.
The actual defense against that class of bug is the runtime heap-gate
(WIFI_MIN_MAX_ALLOC in firmware/src/wifi_net.cpp), which this script does
not replace and cannot substitute for.

Usage:
    python tools/check_static_mem.py                 # check against baseline
    python tools/check_static_mem.py --update-baseline  # accept current usage as the new baseline
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_NAME = "ideaspark_114_st7789"
ELF_PATH = REPO_ROOT / "firmware" / ".pio" / "build" / ENV_NAME / "firmware.elf"
BASELINE_PATH = Path(__file__).resolve().parent / "static_mem_baseline.json"

# Relative growth allowed over the baseline before this fails. A relative
# gate (not an absolute KB number) so legitimate feature growth doesn't
# require touching this script -- just the baseline file, as a deliberate
# one-line diff once the growth is intentional.
ALLOWED_GROWTH = 0.15

TOTAL_DRAM_BYTES = 327680  # matches CLAUDE.md's "327680 bytes" RAM figure


def find_size_tool() -> Path:
    candidates = list(
        (Path.home() / ".platformio" / "packages" / "toolchain-xtensa-esp-elf" / "bin").glob(
            "xtensa-esp32-elf-size*"
        )
    )
    if not candidates:
        sys.exit(
            "xtensa-esp32-elf-size not found under "
            f"{Path.home() / '.platformio' / 'packages' / 'toolchain-xtensa-esp-elf' / 'bin'} "
            "-- has the pioarduino toolchain been installed (run `pio run` at least once)?"
        )
    return candidates[0]


# These are the two sections that actually land in DRAM at runtime.
# NOTE: `size -B`'s generic Berkeley text/data/bss categorization does NOT
# work here -- this project's Xtensa/ESP32 linker script has separate named
# sections per memory region (.dram0.*, .iram0.*, .flash.*, .rtc.*), and
# Berkeley mode's heuristic lumps .flash.rodata (identically-shaped: it's
# read-only initialized data) in with "data", producing a nonsense total
# (measured: 156% of DRAM on a device that boots fine at 18%). Sum the two
# named sections instead -- verified to exactly match pio run's own
# "RAM: used N bytes" figure (59364 bytes here).
DRAM_SECTIONS = (".dram0.data", ".dram0.bss")


def measure(elf_path: Path) -> tuple[int, int]:
    """Returns (dram_used, text) in bytes, parsed from `size -A`'s per-section output."""
    if not elf_path.exists():
        sys.exit(f"{elf_path} not found -- run `pio run -d firmware` first")
    size_tool = find_size_tool()
    out = subprocess.run(
        [str(size_tool), "-A", str(elf_path)], capture_output=True, text=True, check=True
    ).stdout
    sizes: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in DRAM_SECTIONS:
            sizes[parts[0]] = int(parts[1])
    missing = [s for s in DRAM_SECTIONS if s not in sizes]
    if missing:
        sys.exit(f"Section(s) {missing} not found in `size -A` output -- linker script changed?\n{out}")
    dram_used = sum(sizes[s] for s in DRAM_SECTIONS)
    text_line = next((ln for ln in out.splitlines() if ln.strip().startswith(".flash.text")), "")
    text = int(text_line.split()[1]) if text_line else 0
    return dram_used, text


def main() -> int:
    update_baseline = "--update-baseline" in sys.argv[1:]

    static_ram, flash_text = measure(ELF_PATH)
    pct = 100.0 * static_ram / TOTAL_DRAM_BYTES

    print(f"flash .text={flash_text}")
    print(f"Static RAM (.dram0.data + .dram0.bss): {static_ram} bytes ({pct:.1f}% of {TOTAL_DRAM_BYTES})")

    if update_baseline or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps({"static_ram_bytes": static_ram}, indent=2) + "\n")
        print(f"Baseline {'updated' if update_baseline else 'created'}: {BASELINE_PATH}")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text())["static_ram_bytes"]
    limit = int(baseline * (1 + ALLOWED_GROWTH))
    print(f"Baseline: {baseline} bytes (+{ALLOWED_GROWTH:.0%} allowed -> limit {limit} bytes)")

    if static_ram > limit:
        print(
            f"\nFAIL: static RAM grew from {baseline} to {static_ram} bytes "
            f"(+{100 * (static_ram - baseline) / baseline:.1f}%), past the "
            f"{ALLOWED_GROWTH:.0%} threshold.\n"
            "If this growth is intentional, re-run with --update-baseline.\n"
            "If it's NOT intentional, this is exactly the kind of regression "
            "CLAUDE.md gotcha #14 is about -- investigate before flashing."
        )
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
