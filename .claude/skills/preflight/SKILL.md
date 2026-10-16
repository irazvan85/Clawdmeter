---
name: preflight
description: "Pre-flash gates, resource usage report, and on-device performance check for the Clawdmeter firmware. Use before flashing, when asked whether a change is safe to flash, for flash/RAM/IRAM usage or 'how much memory does X use', after adding a global buffer/library/screen, when checking heap headroom, LVGL frame time, loop timing, HTTP latency, or after any change that could affect runtime memory (WiFi, web server, LVGL widgets). Covers tools/preflight.py, tools/resource_report.py, tools/perf_check.py, and the PlatformIO pre-upload hook that runs them."
---

# Preflight: test → resource report → flash → perf check

Two halves, matching the two ways this board has failed before:

| | Static (host, before flashing) | Runtime (device, after flashing) |
|---|---|---|
| Tool | `tools/preflight.py` → `tools/resource_report.py` | `tools/perf_check.py` |
| Sees | link-time budgets: app partition, `.dram0` data+bss, IRAM; largest symbols | heap free / low-water / largest free block, `lv_timer_handler()` time per screen, loop time, HTTP latency |
| Would have caught | a new 20 KB global, a bloated asset, IRAM creep | **gotcha #14** (static RAM sat at 20% while the heap ran out) and **#15** (65 KB screenshot malloc failing under load) |

A pass on the left is **not** a pass on the right. Run both for anything touching memory.

## 1. Before flashing — `tools/preflight.py`

```powershell
python tools\preflight.py            # tests + static guards + pio build + resource gates
python tools\preflight.py --no-build # gates against the existing build
python tools\preflight.py --only static tests   # no toolchain needed
```

Stages: `tests` (stdlib `unittest` in `tools/tests/`), `static` (`check_consistency.py`, `check_auth_gated_routes.py`, `check_web_ui_xss.py`), `build`, `resources`. Prints a PASS/FAIL table; exit 1 on any failure. Failing steps print their full output.

**It also runs automatically**: `firmware/platformio.ini`'s `extra_scripts = pre:scripts/preflight_hook.py` prints the resource summary after every build and runs `preflight.py --no-build` before every `-t upload`, aborting the upload on failure. `CLAWDMETER_SKIP_PREFLIGHT=1` bypasses it for one emergency flash — say so explicitly if you use it.

Daemon tests (`tools/tests/test_daemon.py`) need `httpx`; they skip under PlatformIO's penv python (the hook) and run under `.venv\Scripts\python.exe` / any env with `daemon/requirements.txt`. Run the full suite with httpx at least once per daemon change:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tools\tests -t tools\tests
```

### What the static guards catch (`tools/check_consistency.py`)

`screen-enum`, `cycle-order` (ui.cpp `CYCLE_ORDER[]` == device_config.cpp `CFG_SCREEN_ORDER[]`), `required-bits` (`CLOCK_BIT`/`CONN_BIT`), `web-screen-names` / `web-cfg-screens` (index.html tables vs firmware), `web-ui-fresh` (web_ui.h decompresses to exactly index.html), `splash-index` (every animation JSON is in `_index.json`). The `--only NAME` flag runs one. When adding a screen, the `LABELS` dict at the top of the script needs the new enum value too — that's deliberate (it's the check's reference table).

## 2. Resource report — `tools/resource_report.py`

```powershell
python tools\resource_report.py            # full report: budgets + top-10 DRAM/flash symbols
python tools\resource_report.py --top 25
python tools\resource_report.py --update-baseline   # accept intentional growth
```

Writes `firmware/.pio/build/ideaspark_114_st7789/resource_report.{md,json}`. Gates: app binary ≤ 90% of the 0x3E0000 factory partition, IRAM ≤ 95% of 128 KB, and growth vs `tools/resource_baseline.json` (static DRAM +15%, IRAM +10%, app bin +20%). When a gate trips, the "Largest DRAM symbols" table usually names the culprit directly. Only run `--update-baseline` when the growth is intended, and mention the new numbers in the commit.

`tools/check_static_mem.py` is the older DRAM-only version of the same check; kept for existing callers, superseded by this.

## 3. Flash

See the `run` skill (env vars for gotcha #10 are mandatory on Windows). The pre-upload hook runs step 1 for you.

## 4. After flashing — `tools/perf_check.py`

```powershell
# cold boot + every screen + steady state (opening the port RESETS the device)
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" tools\perf_check.py --serial COM13

# live, no reset: WiFi + HTTP holding their share of heap
.venv\Scripts\python.exe tools\perf_check.py --host clawdmeter.local --token <token>
```

Serial mode: waits for `Dashboard ready`, feeds every payload in `tools/fixtures/payloads.json` (so all 7 lazily-built screens actually get built — gotcha #14), visits screens 0–11 measuring the worst `lv_timer_handler()` pass on each, then a steady-state window. Reports heap after `setup()`, low-water mark, smallest largest-free-block, crash output. HTTP mode times `GET /api/state` (median/p95) and, with `--token`, `GET /api/screenshot.bmp`, then reads the same counters from `/api/state`'s `device` object.

Limits live in `LIMITS` at the top of the script (fail / warn): largest free block < 30 KB fails (< 50 KB warns — `WiFi.begin()` refuses below 50 KB), heap low-water < 25 KB fails, any LVGL pass > 1 s fails (> 300 ms warns), loop avg > 50 ms fails. Writes `perf_report.md` next to the build.

Firmware side: `firmware/src/perf.{h,cpp}` (two `micros()` per loop, `getMaxAllocHeap()` sampled every 64th loop). Serial `perf` prints one JSON line, `perf reset` clears the avg/max window. `heap_min_free` is since-boot and can't be reset.

## Reporting results

Quote the actual numbers (resource table + perf table), not "looks fine". If perf_check was skipped (no device, port busy), say that the runtime side is unverified.
