---
name: run
description: "Build, flash, and screenshot-QA the Clawdmeter ESP32 firmware on Windows. Use whenever building the firmware, uploading/flashing to the device (COM13), capturing a screenshot to verify a UI change, or debugging a device that hangs/crashes after a screen switch or when WiFi is touched. Contains fixes for a known Windows upload hang, a known screenshot-corruption bug, and the LVGL/NVS/WiFi memory gotchas that caused a device hang on first-screen-show — read this before re-diagnosing any of them from scratch."
---

# Build, flash, and QA the Clawdmeter firmware

ESP32-WROOM-32 (ideaspark 1.14" ST7789), no PSRAM, on **COM13** via CH340 USB-serial. See the project's `CLAUDE.md` for hardware/architecture background (gotchas #9-#14 there are the source of truth this skill implements). BLE was removed from the firmware (gotcha #14) — WiFi/HTTP is the sole transport; the daemon POSTs to the device, discovered via mDNS at `clawdmeter.local`.

## Build

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware
```

Every build prints a resource summary (app partition / static DRAM / IRAM, deltas vs `tools/resource_baseline.json`) via `firmware/scripts/preflight_hook.py`.

## Pre-flash gates — automatic, but know what they are

`pio run -t upload` runs `tools/preflight.py --no-build` first (unit tests, screen-table/web-UI consistency, auth-route and XSS guards, resource budgets) and **aborts the upload on failure**. Run it yourself first to see failures without the upload noise:

```powershell
python tools\preflight.py            # includes the build
```

Details, thresholds, and the on-device `tools/perf_check.py` are in the **`preflight` skill** — load it for anything memory- or performance-related. Static gates catch static bloat only, **not** runtime heap exhaustion (gotcha #14 crash-looped at 20% static RAM); `perf_check.py` after flashing is what measures the heap.

## Flash — READ THIS FIRST, before troubleshooting a hang

**Known issue: `pio run -t upload` can hang forever on Windows, with zero output after "Building in release mode".**

Root cause: during the write phase, esptool prints Unicode progress-bar block characters (`█`/`░`). Windows' default console codepage (`cp1252`) can't encode them. PlatformIO's background thread that relays esptool's stdout throws `UnicodeEncodeError` inside that thread — the exception doesn't propagate or print anywhere useful, it just kills the reader silently, and the parent process then blocks forever on a pipe nobody is draining. **This looks identical to a dead USB/bootloader handshake, but it is a pure host-side encoding bug — do not reach for "hold BOOT+EN" first.**

**Always set these before any `pio ... upload` on Windows:**

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware -t upload --upload-port COM13
```

Bash / Bash-tool equivalent:

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$USERPROFILE/.platformio/penv/Scripts/pio.exe" run -d firmware -t upload --upload-port COM13
```

**How to tell the difference if it hangs again:** check the output captured so far.
- Stuck with output ending around `"Building in release mode"` / `"Configuring upload protocol..."` / mid-progress-bar, no error → the codepage bug. Kill the task, re-run with the env vars above.
- Stuck at `"Connecting......"` with no `"Chip type:"` line ever appearing, even with the env vars set → a genuine handshake failure. Then try holding BOOT (GPIO0) while tapping EN, per the hardware note in `CLAUDE.md`.

If a flash is running in the background and you suspect this hang, stop it, re-check the captured output for `UnicodeEncodeError` to confirm, then retry with the fix — don't just wait longer, it will not resolve on its own.

## Screenshot QA (`screenshot.sh`, or the serial `screenshot` command directly)

The board has **no PSRAM**, so `send_screenshot()` (`firmware/src/main.cpp`) cannot buffer a full frame. It streams the redraw as a sequence of tiles as they're flushed:

```
SCREENSHOT_START <w> <h> <raw_size>
A <x1> <y1> <x2> <y2>\n<tile pixel bytes>\n
A <x1> <y1> <x2> <y2>\n<tile pixel bytes>\n
...
SCREENSHOT_END
```

`screenshot.sh` (repo root) already reassembles these tiles into one `w*h*2` frame at their correct offsets (fixed 2026-09-14) — **do not "simplify" it back to a single `port.read(raw_size)`.** That reads the `A ...` text headers as if they were pixel bytes: it doesn't crash or error, it just silently corrupts the image (reads as color-shifted/fringed text, garbled sprites, roughly-plausible-but-wrong colors). If a captured screenshot ever looks like that, this tile-reassembly logic is the first thing to check before assuming a real UI/rendering bug.

Usage on Windows (no ffmpeg/Pillow needed — pure-stdlib PNG writer, pyserial from PlatformIO's penv):

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" tools\screenshot.py out.png COM13
```

`./screenshot.sh out.png COM13` is the bash+ffmpeg equivalent for Linux/macOS. Both reassemble tiles.

**Opening the serial port resets the ESP32** (DTR/RTS). So a serial screenshot can't verify a change made over HTTP (`POST /api/screen`, `/api/config`) — the reset wipes it. Verify HTTP-driven state via `GET /api/state` (`connectivity.screen`) or the token-gated `GET /api/screenshot.bmp` instead.

Other serial QA commands (`check_serial_cmd()` in `main.cpp`), useful for QA without a physical button press:
- `screen <n>` — jump directly to a screen index (bounds-checked against `SCREEN_COUNT`).
- `feed <json>` — inject a payload as if it arrived over `POST /api/payload`, e.g. `feed {"src":"ci","state":"fail",...}`. Also how WiFi credentials get provisioned: `feed {"src":"wifi","ssid":"...","pass":"..."}`.
- `token` — prints the HTTP auth token without needing to read it off-screen (which can be visually cramped) — useful for scripted setup.
- `cfg` — prints the persisted theme index + screen-visibility mask (`theme=N mask=0x3FF`). `cfg <theme> <mask>` sets both directly (device_config.{h,cpp}, Phase 2) without going through the web UI/curl — a mask change needs no restart to test live, a theme change does (see `cycle` below for testing an all-disabled mask safely).
- `cycle` — exercises `ui_cycle_screen()` (the short-press button's code path) without a physical button. Needed to verify visibility-mask changes actually affect navigation, and specifically to verify `cfg 0 0` (every screen disabled) doesn't watchdog-reboot the device — `ui_cycle_screen()`'s traversal loop is bounded with a Clock fallback specifically for this case, and Clock/Connectivity's bits are force-set on by `device_config_set_visible_mask()`/`device_config_init()` regardless of what mask is requested.
- `perf` / `perf reset` — runtime heap + loop/LVGL timing as one JSON line (see the `preflight` skill).
- `timer`, `histfill`, `histclear`, `uhistfill`, `uhistclear`, `i2cscan`, `gpiotest` — see CLAUDE.md's "QA your own UI changes" section for the full list.

## Suggested workflow for a UI change

1. Edit `firmware/src/ui.cpp` (or wherever).
2. `python tools\preflight.py` — build + all host gates + resource report. Read the resource table's deltas.
3. Flash with the env vars above (the pre-upload hook re-runs the gates).
4. `feed` synthetic data for the screen you're checking (`tools/fixtures/payloads.json` has one valid payload per `src`), `screen <n>` to jump to it, then screenshot and read the PNG.
5. `tools\perf_check.py --serial COM13` — worst LVGL pass per screen + heap low-water. Quote the numbers.
6. Iterate without asking the user to press the physical button.

Adding or reordering a screen? Load the **`add-screen`** skill first — it lists the ~8 tables that must change together.

## Device hangs or crashes after a screen switch, WiFi change, or NVS/`Preferences` change

**Don't assume a new bug — this board has hit four specific, now-fixed classes of this before (CLAUDE.md gotchas #11-14). Check those first.**

Fast triage, cheapest first:
- **Crashes with a backtrace** (`Guru Meditation Error` / `assert failed`) right after opening a `Preferences` namespace, especially one that's brand new → gotcha #11 (open read-write, not read-only, for anything that might be the first-ever access).
- **Crashes or hangs specifically when WiFi/the web server touches the network** (right around `WiFi.mode()`/`server.begin()`/`handleClient()`) → gotcha #12 (don't call `WebServer::begin()` until `WIFI_STATE_CONNECTED`; don't call `WiFi.mode()` at all until real credentials exist).
- **Hangs silently (no crash, no backtrace) the first time a screen is shown**, especially one with many widgets, and heap looks fine (`ESP.getFreeHeap()` healthy) → check LVGL's *own* pool, not general heap: `lv_mem_monitor_t mon; lv_mem_monitor(&mon);` right before/after the `ui_show_screen()` call that hangs (only meaningful if `LV_USE_STDLIB_MALLOC` was ever reverted to `LV_STDLIB_BUILTIN`/a fixed `LV_MEM_SIZE` — as shipped, this project uses the CLIB allocator, see gotcha #13, precisely to make this whole class of bug structurally impossible). If someone reintroduces `LV_MEM_SIZE`, this is the first thing to check — a high `used_pct` / small `free_biggest_size` right after `ui_init()` means there's no headroom left for a redraw, and `lv_timer_handler()` hangs (not fails) rather than erroring.
- **A clean `Guru Meditation Error (StoreProhibited)` crash with a null-ish `EXCVADDR` (a small offset like `0x54`, not a wild address), especially inside LVGL widget creation** → heap exhaustion during `ui_init()` or a lazy screen build, not a widget-specific bug. Decode the `Backtrace:` line with `xtensa-esp32-elf-addr2line.exe -pfiaC -e .pio\build\ideaspark_114_st7789\firmware.elf <addrs...>` (toolchain under `%USERPROFILE%\.platformio\packages\toolchain-xtensa-esp-elf\bin\`) — instant `file:line`, including through inlined calls, far faster than bisecting with prints. See gotcha #14 for the full incident this pattern came from.
- **Anything that changes overall RAM footprint** (new global buffer, a library added/removed, a new screen's worth of eager widgets) → `python tools\resource_report.py --top 25` first (names the largest DRAM symbols), then `tools\perf_check.py --serial COM13` for the runtime heap; a serial `perf` command prints the live counters at any time.

Bisection technique that worked (cheap to redo if a *new* hang ever shows up): add `Serial.println()` checkpoints immediately before/after each call in `loop()` and `setup()` — pair every checkpoint with `Serial.flush()`, since a crash immediately after a print can eat the print itself if it hasn't drained the UART's TX buffer yet — rebuild/reflash, reproduce, and grep the capture for the last checkpoint that printed. An **unconditional** print (not gated by a once-per-second heartbeat) around the *specific* suspect call is what actually pins down a hang inside a library function like `lv_timer_handler()` — a throttled checkpoint only proves general loop() liveness, not that one specific call returns. Remove all checkpoints once the root cause is confirmed; don't ship them.

When testing over serial, don't `time.sleep()` through a "let it settle" window without reading during the sleep — a silent second reset (or a genuinely-hung device) looks identical to "nothing happened yet" if the port isn't being drained the whole time. Read continuously instead (see gotcha #14's testing note).
