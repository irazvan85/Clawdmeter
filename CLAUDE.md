# Project context

ESP32 firmware for a desk-side Claude Code usage monitor on an **ideaspark ESP32 1.14" ST7789** board (135×240 IPS SPI LCD). Connects to a host daemon over WiFi/HTTP (BLE was removed, see gotcha #14); daemon polls Anthropic API for usage data.

This file is for future Claude Code sessions to bootstrap quickly. Read this first.

## Hardware (critical pins)

- MCU: **ESP32-WROOM-32** (240 MHz, 320 KB SRAM, 4 MB Flash, **no PSRAM**, BLE 4.2)
- Display: **ST7789** 135×240 IPS via SPI — MOSI=23, SCLK=18, CS=15, DC=2, RST=4, BLK=32
- Touch: **none**
- PMU: **none** (no battery, no AXP)
- IMU: **none** (no auto-rotation; rotation fixed at 0)
- USB-serial: CH340 on **COM13** (Windows)
- MQ-135 gas sensor (optional): module V -> 5V, G -> GND, S -> 10k -> **GPIO 34**, plus 10k GPIO 34 -> GND (divider halves the 0-5 V output; `GAS_DIVIDER` in `gas_sensor.h`). Must be an ADC1 pin (32-39) — ADC2 is dead while WiFi is up. Keep it away from the BME280: the heater warms its surroundings.
- Buttons: GPIO 0 (back/left button only). GPIO 18 is LCD SCLK — **cannot be used as button**.
  Short press = cycle screen. Long press (≥700 ms) = context action: on Connectivity, forget the stored WiFi network; on Clock, toggle the focus timer; on Air, set the MQ-135 clean-air baseline (same as serial `gascal` / dashboard "Calibrate baseline" → token-gated `POST /api/gas action=cal|auto`; refused while the heater is warming); elsewhere, no effect beyond the flash feedback (used to request an immediate daemon poll over BLE — dropped when BLE was removed, see gotcha #14).

## Architecture

```text
main.cpp        — setup(), loop(), BTN_BACK (GPIO0) short/long-press polling, serial commands (screenshot, etc.)
display_cfg.h   — pin defines (ST7789 SPI), LCD_WIDTH=135, LCD_HEIGHT=240, extern bus/gfx objects
ui.{h,cpp}      — 13-screen UI (see Screens below); redesigned for 135×240
splash.{h,cpp}  — 20×20 pixel-art animation engine; 6× upscale (120×120) on splash, 4× (80×80) on Copilot screen
env_sensor.{h,cpp} — BME280/BMP180 dispatcher; owns Wire.begin(21, 22)
gas_sensor.{h,cpp} — MQ-135 on GPIO 34 (ADC1): oversampled + smoothed reading,
                   Rs/R0 against a clean-air baseline (auto-tracks the cleanest
                   reading until serial `gascal` pins it; NVS namespace "gas"),
                   temp/humidity-compensated from env_sensor when present,
                   180 s heater warm-up. Headline level comes from Rs/R0 alone;
                   GAS_DEFS[] applies the datasheet curves (MQSensorsLib fits,
                   clean air = 3.6 in datasheet terms) to that one ratio for
                   CO2/NH3/alcohol/toluene/acetone/CO *equivalents* -- one
                   sensor can't separate gases, so they move together. Also a
                   spike-vs-gradual "likely source" hint (heuristic). Pinned by
                   tools/tests/test_gas_table.py.
sensor_hist.{h,cpp} — 24 h ring buffer of sensor readings (96 × 15 min), persisted to NVS
                   (temp/hum/press from env_sensor, plus SH_AQ = Rs/R0 x1000 from
                   gas_sensor via its own sensor_hist_sample_aq() -- the ratio, so
                   every gas equivalent is derivable from history)
usage_hist.{h,cpp}  — 24 h ring buffer of Claude session/weekly usage % (same
                       design as sensor_hist, kept as a sibling module — see
                       usage_hist.h for why), feeds the Usage screen sparklines
imu.{h,cpp}     — stub: imu_get_rotation() always returns 0
power.{h,cpp}   — stub: battery=-1, charging=false, pwr_pressed=false
device_config.{h,cpp} — web-configurable theme + screen-visibility settings
                   (Phase 2), NVS-backed (namespace "cfg", read-write open
                   per gotcha #11). g_theme is read directly by theme.h's
                   macros; a theme change needs an ESP.restart() to apply
                   (LVGL has no live-restyle hook), visibility changes apply
                   live. device_config_screen_enabled() is consulted only by
                   navigation (ui_cycle_screen()/refresh_screen_dots() in
                   ui.cpp, via a screen_in_cycle() wrapper) — never by
                   screen_is_populated(), which stays a pure has-data check
                   so the serial `screen <n>` QA command can always reach a
                   user-hidden screen. Its CFG_SCREEN_ORDER[] mirrors
                   ui.cpp's CYCLE_ORDER[] bit-for-bit; keep both in sync.
wifi_net.{h,cpp} — WiFi STA connectivity — the sole transport (BLE was
                   removed, see gotcha #14). Only connects once credentials
                   exist (provisioned as a one-time manual step over the
                   serial `feed` command — see "wifi" in data.h/main.cpp),
                   so it costs nothing (RAM or otherwise) until provisioned.
                   Also owns the HTTP auth token (wifi_get_token()).
discovery.{h,cpp} — UDP (port 42424) discovery responder, the daemon's
                   fallback for finding the device when mDNS/`.local`
                   resolution isn't available or the IP has drifted (DHCP
                   renewal, router reboot, etc.). discovery_init() is a
                   no-op until WiFi is connected; discovery_tick() (called
                   from loop(), right after web_server_tick()) lazily
                   binds a WiFiUDP socket on first connected tick, then
                   each subsequent tick does a non-blocking parsePacket(),
                   and replies only to a datagram whose payload matches
                   DISCOVERY_REQUEST ("CLAWDMETER_DISCOVER_V1") exactly,
                   sending DISCOVERY_REPLY ("CLAWDMETER_HELLO_V1") back to
                   udp.remoteIP()/remotePort(). Unauthenticated by design,
                   same threat-model tradeoff as GET /api/state — the reply
                   carries no secret, and the asking client trusts only the
                   UDP packet's source IP (never anything in the payload),
                   so there's nothing here to spoof usefully. See "Daemon /
                   host side" below for the client (daemon + standalone
                   tools/discover_device.py) side of the protocol.
web_server.{h,cpp} — HTTP dashboard/state/data-ingest server (port 80, stock
                   WebServer, no lib_deps) plus an mDNS responder
                   (clawdmeter.local) so the daemon can find the device.
                   Routes registered at boot; server.begin()/MDNS.begin()
                   deliberately deferred until WiFi actually has an IP (see
                   CLAUDE.md gotcha #12). POST /api/payload (token-gated,
                   see wifi_get_token()) is the daemon's data-push path,
                   replacing BLE's RX characteristic. GET/POST /api/config
                   (Phase 2) read/write the theme + screen-visibility
                   settings in device_config.{h,cpp}; POST is token-gated
                   and form-encoded (not JSON, unlike /api/payload — no
                   JsonDocument needed for two small fields). A theme-change
                   POST replies before restarting (ESP.restart() inside a
                   handler would tear down the socket before the response
                   drains) — the actual restart is deferred a beat and
                   applied from web_server_tick(). POST /api/screen
                   (token-gated, form-encoded) lets the web dashboard change
                   what's on the device's screen remotely — `n=<0..12>`
                   jumps straight to a screen_t index (ui_show_screen(),
                   which already redirects an unpopulated/out-of-range
                   index to Clock), `action=next` advances one step
                   (ui_cycle_screen(), which already skips hidden/
                   unpopulated screens) — the same two actions the
                   physical button offers, just over HTTP instead of GPIO0.
                   Both guards are reused as-is, nothing is duplicated in
                   the handler. Response echoes the resulting index via
                   ui_get_current_screen(); that same getter also feeds a
                   new `connectivity.screen` field in GET /api/state's JSON
                   (build_state_json(), main.cpp) so the dashboard's nav
                   hint can show the device's actual current screen without
                   a round trip through the screenshot route.
device_api.h    — (GET /api/state also carries `indoor` -- env sensor temp/pressure/
                   humidity, null where the chip can't measure -- and `air`.)
device_api.h    — build_state_json()/capture_screenshot_streamed()/
                   device_ingest_payload(), implemented in main.cpp (owns
                   the data), declared here so web_server.cpp can reach
                   them without main.cpp's statics leaving main.cpp.
                   capture_screenshot_streamed() invokes a callback per
                   flushed tile rather than filling a caller-provided
                   buffer -- GET /api/screenshot.bmp used to malloc() one
                   ~65 KB full-frame buffer and fail under real load; see
                   gotcha #15.
perf.{h,cpp}    — runtime counters: loop()/lv_timer_handler() time, heap free /
                   low-water / largest free block (sampled every 64th loop).
                   Serial `perf` (one JSON line) / `perf reset`; also the
                   `device` object in GET /api/state. Read by
                   tools/perf_check.py -- the runtime counterpart to the static
                   resource report (see the `preflight` skill).
web_ui.h        — generated by tools/build_web_ui.js from tools/web_ui/index.html
                   (gzip'd PROGMEM byte array) — do not hand-edit.
data.h          — UsageData, CodexData, CopilotData, SysInfoData, VscodeData, CiData, EnvData,
                   AuroraData, TodayData structs (one per payload "src")
icons.h         — icon arrays (RGB565)
logo.h          — 80×80 RGB565 logo (hidden at runtime — too wide for 135px)
font_*.c        — LVGL 9 bitmap fonts in use: Tiempos 34, Styrene 24/16/14/12, Mono 18
splash_animations.h — generated, do not hand-edit
```

## Screens

`screen_t` in `ui.h` (SCREEN_COUNT = 15; the `SCREEN_BLUETOOTH` enum name is unchanged — purely cosmetic to rename now that its content is WiFi-only, on-screen title is already "Connectivity"). Short-press cycles in this order, skipping any screen that has never received data from the daemon: Clock → Aurora → Sensor → Sensor Trend → Usage → Copilot → SysInfo → VS Code → Connectivity → CI (labeled "Checks" in UI) → Today → Codex → Air → Gases → Splash → Clock…

| Screen | Payload `src` | Shows |
| --- | --- | --- |
| `SCREEN_SPLASH` | — | Boot animation; default screen, only advances on button press |
| `SCREEN_CLOCK` | `env` | Time/date, weather (temp, hi/lo, condition, location), a Claude+Copilot usage strip; long-press toggles the focus timer |
| `SCREEN_AURORA` | `aurora` | Aurora borealis visibility forecast for the Clock screen's location: local probability % (NOAA OVATION nowcast), Kp gauge, peak-next-24h, daylight/cloud caveat, pixel-art shimmer animation |
| `SCREEN_SENSOR` | on-device I2C | BME280/BMP180 temp/humidity/pressure + sparkline; skipped if no sensor wired |
| `SCREEN_SENSOR_GRAPH` | on-device I2C | 24 h trend panels (see `sensor_hist.{h,cpp}` below) |
| `SCREEN_USAGE` | `claude` (default `src`) | Session (5 h) and weekly (7 d) % bars, reset countdowns, active model + activity status word |
| `SCREEN_CODEX` | `codex` | Account quota percentages, dynamic window labels/reset countdowns, plan and sample freshness; no history buffers. ID 12, appended visibility bit 11. |
| `SCREEN_COPILOT` | `copilot` | Premium-request % used, remaining/total, reset date, plan name |
| `SCREEN_SYSINFO` | `sysinfo` | Host CPU/RAM/disk % and temp |
| `SCREEN_VSCODE` | `vscode` | VS Code process RSS, CPU %, extension host count, recent error |
| `SCREEN_BLUETOOTH` | — | Titled "Connectivity" on-screen. WiFi state, IP + HTTP auth token + mDNS hostname once connected (else the connection state), hold-to-forget-network hint |
| `SCREEN_CI` | `ci` | Up to four priority-ordered items rotating every 8 s: repo, PR/title, actual run branch/SHA, workflow, failing job/step, review queue and local git summary. Dashboard provides check/PR links. |
| `SCREEN_TODAY` | `sum` | Daily digest: active minutes, tokens, cost, commits, Copilot requests used |
| `SCREEN_AIR` | on-device ADC | MQ-135 air quality: level word (Good/Fair/Poor/Bad, from Rs/R0), Rs/R0 + bar, status line (warm-up / likely-source hint / output voltage), auto/cal baseline, 24 h Rs/R0 trend. Built lazily on the first reading with something on GPIO 34. ID 13, visibility bit 12. |
| `SCREEN_GASES` | on-device ADC | Per-gas ppm *equivalents* of the same MQ-135 reading (CO2, NH3, Alcohol, Toluene, Acetone, CO), coloured against each gas's thresholds; "<10"/">max" outside the datasheet range. Built with Air. ID 14, visibility bit 13. |

`act` payloads (`ui_update_act`) don't own a screen — they drive the activity dot/word on Usage and, on `ACT_NEEDS_INPUT`, a persistent "Claude needs you" banner that overlays whatever screen is active until dismissed by a press. The focus timer (Clock long-press) uses the same banner widget for a transient "Focus"/"Break time" message.

## Build / flash (Windows)

```powershell
# Build
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware

# Flash (PYTHONIOENCODING avoids the upload hang in gotcha #10)
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware -t upload --upload-port COM13
```

Device is on COM13 via CH340 USB-serial. Hold BOOT (GPIO0) while pressing EN if the chip doesn't enter download mode automatically (rarely needed). If an upload appears to hang with no output after "Building in release mode", see gotcha #10 — it's very likely the codepage issue, not a real hardware/handshake failure.

## QA your own UI changes — don't ask the user

The `run` project skill (`.claude/skills/run/SKILL.md`) has the full build/flash/screenshot workflow, including the fixes for gotchas #9 and #10 below — load it before troubleshooting a hang or a garbled screenshot from scratch.

The firmware ships a `screenshot` serial command that dumps the LVGL framebuffer over the serial port. `./screenshot.sh out.png COM13` (or the Windows equivalent) captures a 135×240 PNG. **Use this on every UI iteration** — read the PNG, verify visually, iterate.

The boot screen is `SCREEN_SPLASH` and only advances on a physical button press. To screenshot a different screen without asking the user to press a button, **temporarily change the default boot screen** in `main.cpp` (search for `ui_show_screen(SCREEN_SPLASH);`) to any value from the `screen_t` enum (see Screens above), iterate, then revert before committing. Alternatively, use the serial QA commands without touching code: `screen <N>` jumps to a screen index directly, and `feed <json>` injects a payload (e.g. `feed {"src":"ci","state":"fail",...}`) as if it arrived over BLE — see `check_serial_cmd()` in `main.cpp` for the full command list (`token`, `cfg`, `cycle`, `timer`, `gas`, `gascal`, `gasauto`, `histfill`, `histclear`, `uhistfill`, `uhistclear`, `i2cscan`, `gpiotest`, `perf`, `perf reset`).

## Critical gotchas

1. **pioarduino platform required.** GFX Library for Arduino 1.6.x needs Arduino Core 3.x (`esp32-hal-periman.h`), which standard `espressif32` 7.x does NOT provide. We use `pioarduino/platform-espressif32` (stable zip URL in platformio.ini). Standard `espressif32` gives Core 2.x → compile failure.
2. **No PSRAM.** ESP32-WROOM-32 has no SPIRAM. All `heap_caps_malloc(…MALLOC_CAP_SPIRAM)` must be plain `malloc()`. LVGL partial render buffers are 135×16×2 = 4,320 bytes each (`BUF_LINES` in `main.cpp` — was 40/10,800 bytes before WiFi joined the build, trimmed for heap headroom; see gotcha #13).
3. **ST7789 col/row offsets.** The 1.14" 135×240 panel needs `col_offset=52, row_offset=40` in `Arduino_ST7789` constructor or the image is shifted off-screen.
4. **GPIO 18 = LCD SCLK.** Cannot be used for any other purpose (was BTN_FWD on the old board). BTN_FWD/right-button is permanently disabled.
5. **Check flash before adding large assets.** The partition scheme (`firmware/partitions_app.csv`) gives a single ~3.9 MB app partition — reclaimed from a wasted second OTA slot when WiFi joined the build (see gotcha #12). Flash is no longer the tight resource here (`Flash: 39.1%` as of 2026-09-15, after BLE removal — was 44.3% with NimBLE-Arduino still in the build); RAM is — see gotcha #13. Still, check `pio run`'s own report (or `tools/check_static_mem.py`) before adding large new assets rather than trusting any number in this doc.
6. ~~NimBLE-Arduino 2.5.0 deprecation warning.~~ **No longer applicable — BLE was removed entirely** (`ble.{h,cpp}` deleted, `NimBLE-Arduino` dropped from `platformio.ini`'s `lib_deps`); see gotcha #14. Kept as a numbered placeholder rather than renumbering everything below.
7. **LVGL 9 font patching.** `lv_font_conv` outputs LVGL 8 format. Must remove `#if LVGL_VERSION_MAJOR >= 8` guards, drop `.cache` field, add `.release_glyph`, `.kerning`, `.static_bitmap`, `.fallback`, `.user_data`. Without patching, fonts render invisible.
8. **LVGL RGB565A8 is planar.** `w*h` RGB565 pixels followed by `w*h` alpha bytes; `data_size = w*h*3`, `stride = w*2`. Use `init_icon_dsc_rgb565a8()` for icons that overlap non-uniform backgrounds. Lucide source PNGs are black-on-transparent — converter must tint to white. See `tools/png_to_lvgl.js`.
9. **Screenshot protocol is tiled, not one blob.** Because there's no PSRAM for a full framebuffer, `send_screenshot()` (`main.cpp`) streams each LVGL-flushed tile as `A <x1> <y1> <x2> <y2>\n<tile pixel bytes>\n`, repeated until `SCREENSHOT_END` — a full 240-tall redraw is ~15 tiles (135×16 partial buffers, `BUF_LINES`). `screenshot.sh`'s reader reassembles tiles into one `w*h*2` frame at their `(x1,y1)` offsets; do not revert it to a single `port.read(raw_size)` — that reads the `A ...` headers as if they were pixel bytes and corrupts the image (looks like color-shifted/fringed text, not a crash).
10. **Windows console codepage breaks `pio run -t upload`.** esptool's progress-bar glyphs aren't representable in the default `cp1252` console codepage; PlatformIO's output-relay thread throws `UnicodeEncodeError` mid-upload and the process hangs (looks identical to a genuine stuck flash — no further output, no exit). Fix: set `PYTHONIOENCODING=utf-8` (and `PYTHONUTF8=1`) in the environment before running any `pio ... upload` command on Windows.
11. **`Preferences::begin(ns, true)` (read-only) crashes on a namespace that has never been created.** Hits `assert failed: xQueueSemaphoreTake` right after the expected `nvs_get_*` `NOT_FOUND` log — reproduces even on a freshly-erased NVS partition, so it's not data corruption. Always open `Preferences` read-write (`begin(ns, false)`) for anything that might be the first-ever access to that namespace; read-write auto-creates it instead of hitting the crashing path. Affects `sensor_hist.cpp`, `usage_hist.cpp`, `wifi_net.cpp` — all three were fixed this way.
12. **`WebServer::begin()` before WiFi has a real IP either crashes or hangs.** Calling it too early (lwIP's tcpip task not yet up) asserts inside `xQueueSemaphoreTake` via `lwip_socket`; calling it once `WiFi.mode()` has run but before an IP is assigned can instead hang `handleClient()` silently. Fix (`web_server.cpp`): `web_server_init()` only registers routes; `web_server_tick()` defers the actual `server.begin()` until `wifi_get_state() == WIFI_STATE_CONNECTED`. Relatedly, `wifi_net.cpp`'s `wifi_init()` skips `WiFi.mode()` entirely when no credentials are stored yet — WiFi costs nothing (RAM or otherwise) until the user actually provisions it.
13. **LVGL's builtin allocator (fixed `LV_MEM_SIZE` static pool) cannot coexist with WiFi on this board.** WiFi/lwIP's own static footprint (~15 KB, from prebuilt `libnet80211.a`/`liblwip.a` — not tunable, they're prebuilt binaries) pushed the DRAM link budget too tight for a pool big enough to survive real use: any size that links (≤~56 KB) leaves so little runtime headroom (measured 96% used, ~500-byte biggest free block right after `ui_init()`) that `lv_timer_handler()` hangs — not fails, hangs — redrawing a multi-widget screen for the first time. **Fixed by switching allocators**, not by tuning the pool size: `-DLV_USE_STDLIB_MALLOC=1` (CLIB) in `platformio.ini` makes LVGL draw from the same general heap as everything else (~70+ KB free at runtime) instead of a separate fixed reservation — this also dropped static RAM usage from 37.7% to 20.5%. `LV_MEM_SIZE` is a no-op once this is set. Also freed ~23 KB of *heap* (not static, but same underlying pressure) by sharing one canvas buffer across the mutually-exclusive Splash/Copilot/Aurora screens instead of each permanently holding its own — see `get_shared_canvas_buf()` in `splash.cpp`. If a screen ever hangs on first show again, suspect this class of issue first: reproduce with `screen <n>` over serial, and check whether it's heap/pool-related before assuming a widget-specific bug.
14. **Eagerly building the full 12-screen UI doesn't fit in heap once WiFi is primed — and this board's total heap budget is genuinely too tight for [full UI] + [full BLE incl. HID] + [live WiFi] all at once, regardless of init order.** This took an entire session to pin down because every attempted fix produced a *different*-looking failure (crash-loop, silent hang, black screen) depending on where in the boot sequence the shortfall landed — each looked like a new bug, but they were all the same underlying resource ceiling:
    - Building all 12 screens' widgets in `ui_init()` *before* `wifi_init()` (the original order) leaves ui_init() plenty of heap, but then `esp_wifi_start()` (triggered by `WiFi.mode()`) fails with `ESP_ERR_NO_MEM` — and instead of failing cleanly, the WiFi driver task spins without yielding, starves `IDLE0`, and the task watchdog force-reboots the device in a crash-loop (every ~8s, since the bad credentials are already persisted and retried every boot).
    - Priming WiFi's one-time `esp_wifi_start()` allocation (~52 KB) *before* `ui_init()` instead (so it grabs a big contiguous block while the heap is still unfragmented) fixes *that* crash — but then `ui_init()` itself runs out of heap building all 12 screens, and LVGL's `lv_obj_class_create_obj()` (which doesn't null-check its internal allocation) writes through a null pointer: a clean, 100%-reproducible `Guru Meditation Error (StoreProhibited)`, easy to pin down with `xtensa-esp32-elf-addr2line.exe -pfiaC -e firmware.elf <backtrace addrs>` against the crash dump's backtrace line.
    - **Fix: build only the always-reachable screens (Clock/Usage/Copilot/Connectivity/Splash — the `default: true` cases in `screen_is_populated()`) eagerly in `ui_init()`.** The other 7 (sysinfo/vscode/ci/today/aurora/sensor/sensor-graph) are gated behind a `*_has_data` flag already (only shown once real data arrives) — so each one's `init_X_screen()` call was moved out of `ui_init()` and into the top of its own `ui_update_X()`, guarded by `if (!X_has_data) init_X_screen(lv_screen_active());`. Sensor+trend share one non-sticky flag (`sensor_has_data` toggles on transient I2C errors), so they use a dedicated sticky `sensor_created` flag instead, to avoid rebuilding widgets on every recovery. This spreads the 12 screens' worth of allocation out over the session instead of all at boot, and was enough to get `ui_init()` reliably under budget.
    - **This lazy-build change has one sharp edge, and it bit this session too**: `ui_show_screen()` unconditionally hides *all twelve* screen containers at the top of every call (`lv_obj_add_flag(X_container, LV_OBJ_FLAG_HIDDEN)`), regardless of which screen is being shown. Once 7 of those containers can legitimately be null (not yet built), that line needs a null-guard per lazy container (`if (X_container) lv_obj_add_flag(...)`) — missing this produces a crash on the *very first* `ui_show_screen()` call of any boot (i.e. `ui_show_screen(SCREEN_SPLASH)` in `setup()`), which looks exactly like a silent hang (no crash dump captured because the test's monitor window had already moved on, BLE goes quiet because `loop()`/`ble_tick()` never run again) rather than an obvious null-deref. Any code that iterates/touches all screen containers unconditionally needs the same audit whenever a screen becomes lazily-built.
    - `ui_show_screen(screen)` also now redirects to `SCREEN_CLOCK` if `!screen_is_populated(screen)` — `ui_cycle_screen()` already skipped unpopulated screens, but the serial `screen <n>` QA command jumps directly and needs the same guard against a still-null container.
    - **Even after both of the above, don't skip a heap check before `WiFi.begin()` too, and don't set its threshold too low.** `WiFi.mode()`/`esp_wifi_start()` and `WiFi.begin()` each need their own guard — `WiFi.begin()` itself is cheap, but a too-low threshold (this session tried 15 KB) lets it through at a heap level that's merely "enough for the call to return", not "enough for the device to keep running afterward": a live BLE GATT write arriving minutes later hit a C++ allocation failure inside NimBLE's own write handler (`ble.cpp`'s `RxCallbacks::onWrite` → `NimBLEAttValue` → `std::string` alloc → `std::terminate()`/`abort()`) — a crash with nothing to do with WiFi's own code path, just a symptom of the same underlying low-heap condition. Both `WiFi.mode()`'s and `WiFi.begin()`'s guards now share the same conservative bar (`WIFI_MIN_MAX_ALLOC` = 90 KB max-alloc) in `wifi_net.cpp`. **Practical consequence on this board as shipped: with the full BLE (incl. the HID keyboard service) + full UI feature set active, post-`ui_init()` max-alloc sits at ~32–45 KB, under that bar — so WiFi mostly stays in `WIFI_STATE_FAILED`/deferred rather than actually connecting.** That's the safe outcome (never crashes), not a bug; getting WiFi to actually connect reliably on this hardware needs *more* heap freed elsewhere (e.g. dropping the BLE HID service, or auditing the remaining 5 eager screens) — that work hasn't been done yet.
    - Reproduction/diagnosis technique worth keeping: a plain build (Arduino core, no ESP-IDF project) still supports `xtensa-esp32-elf-addr2line.exe` against `.pio/build/<env>/firmware.elf` — feed it the space-separated hex addresses straight from a `Guru Meditation Error`'s `Backtrace:` line (`-pfiaC -e firmware.elf <addrs...>`) and it resolves straight to `file:line`, including through inlined calls. Far faster than bisecting with print statements once you actually have a crash dump instead of a silent hang.
    - Testing gotcha: don't `time.sleep()` through a "let it settle" window in a serial test script without reading during the sleep — a silent second reset (or a genuinely-hung device) looks identical to "nothing happened yet" if you're not draining the port the whole time. Read continuously instead; it costs nothing and turns "no response, not sure why" into an immediate answer.
    - **Resolution (same day, follow-up session): BLE was removed from the firmware entirely** rather than continuing to chase headroom for three memory-hungry subsystems at once — see the "Remove BLE, WiFi-only" session highlight below. **Verified working**: WiFi connects and the daemon runs a full real poll cycle over HTTP with zero crashes — the first time all session. The heap-gate mechanism (`WIFI_MIN_MAX_ALLOC`/`WIFI_MIN_MAX_ALLOC_BEGIN`) was kept as defense-in-depth and re-tuned based on real post-removal measurements (~82 KB max-alloc, not the "comfortably above 90 KB" originally hoped for) rather than assumed safe without checking.
15. **A single large `malloc()` for `GET /api/screenshot.bmp` failed with "out of memory" under real load** (WiFi connected + an active daemon posting data every few seconds) — `handle_screenshot()` (`web_server.cpp`) used to allocate `LCD_WIDTH*LCD_HEIGHT*2` (~65 KB) as one contiguous block to hold the full captured frame before streaming it out as a BMP, and that single allocation is exactly the kind this board's heap can't reliably satisfy once WiFi + HTTP + an active connection are all holding their own share (same underlying resource class as gotcha #14, different call site — this one just hadn't been exercised over real HTTP traffic yet when gotcha #14 landed). **Fix: stream tile-by-tile instead of buffering the whole frame**, mirroring the serial `screenshot` command's approach (`send_screenshot()`/`my_flush_cb()` in `main.cpp`), which has never needed a full-frame buffer and has been reliable all session. `capture_screenshot_streamed()` (`device_api.h`/`main.cpp`) invokes a callback once per ~16-row tile as LVGL flushes it (`shot_cb` in `my_flush_cb()`, replacing the old `shot_fb` buffer-copy sink); `web_server.cpp`'s callback converts each tile to BGR888 into a small (~6.5 KB max) per-tile buffer and `server.sendContent()`s it immediately — no allocation anywhere in the path. The BMP header declares a **negative height** (`write_le32(&hdr[22], (uint32_t)-h)`) specifically so rows can be written in LVGL's natural top-down flush order without buffering/reversing — this is a standard, widely-supported BMP variant (Windows GDI has supported top-down DIBs since Windows 3.1; every modern browser's `<img>` BMP decoder handles it), not a hack. Verified: 5 consecutive `GET /api/screenshot.bmp` requests all succeeded (HTTP 200, correct 97,974-byte size, valid decodable image) while the daemon was actively posting in the background, and the daemon's own writes were completely undisturbed by the concurrent requests.

## Icons

`tools/png_to_lvgl.js <input.png> <symbol> [W_MACRO] [H_MACRO] [--tint=RRGGBB | --no-tint]` converts an alpha PNG to RGB565A8. Default tint is white (`0xFFFFFF`) — necessary for Lucide PNGs. Splice output into `firmware/src/icons.h` and use `init_icon_dsc_rgb565a8()` in ui.cpp.

## Splash animations

16 × 20×20 pixel-art animations. 13 sourced from [claudepix.vercel.app](https://claudepix.vercel.app) (splash screen). 3 are manually authored (`copilot_idle.json`, `copilot_thinking.json`, `aurora_shimmer.json`). Pipeline:

```bash
node tools/scrape_claudepix.js  # → tools/claudepix_data/*.json (claudepix only)
node tools/convert_to_c.js      # → firmware/src/splash_animations.h (all 16)
```

Each animation has a per-animation palette (up to 10 colors). Cell values index it. Splash screen renders at 6× scale (120×120). Copilot and Aurora screens each render at 3× scale (60×60) via their own canvas (`splash_copilot_init`/`splash_aurora_init` in `splash.cpp`). Copilot cycles between `copilot_idle` (10s) and `copilot_thinking` (5s); Aurora just loops `aurora shimmer`.

**Every hand-authored (non-scraped) animation must be listed in `tools/claudepix_data/_index.json`** — `convert_to_c.js` only emits what's indexed there, and fully regenerates `splash_animations.h` from scratch each run. `copilot_thinking.json` existed as a file but was missing from `_index.json` (silently hand-patched into `splash_animations.h` at some point, despite the file's own "do not hand-edit" header) — running the documented regen pipeline without fixing the index first will silently drop it. Do not hand-edit `splash_animations.h` — regenerate with `convert_to_c.js`.

## Skills & tooling (load the skill, don't re-derive)

Project skills live in `.claude/skills/` (versioned):

| Skill | Use for |
| --- | --- |
| `run` | build, flash (gotcha #10 env vars), serial screenshot QA, hang/crash triage |
| `preflight` | pre-flash gates, resource report, on-device perf/heap check |
| `add-screen` | every table a new/reordered screen must touch |
| `payload-contract` | HTTP routes, auth, payload keys, discovery, daemon rules |
| `assets` | web_ui.h, splash animations, icons, LVGL-9 font patching |

Pipeline: `python tools/preflight.py` (unit tests in `tools/tests/`, `check_consistency.py`, auth/XSS guards, `pio run`, `resource_report.py`) → flash (PlatformIO's pre-upload hook `firmware/scripts/preflight_hook.py` re-runs the gates and aborts on failure; `CLAWDMETER_SKIP_PREFLIGHT=1` overrides) → `tools/perf_check.py --serial COM13` / `--host <ip> --token <t>` (runtime heap, LVGL frame time, HTTP latency, via `firmware/src/perf.{h,cpp}` — serial `perf` / `perf reset`, `/api/state` `device` object). Library and platform versions are pinned exactly in `platformio.ini`; bump deliberately and re-run both checks.

Claude Code hooks (`.claude/settings.json` → `.claude/hooks/`): editing `tools/web_ui/index.html` regenerates `web_ui.h`; editing `web_server.cpp` runs the auth-route guard; editing screen tables runs `check_consistency.py` — a failing guard is fed back immediately.

`.github/` (Copilot agents/skills/instructions) and `AGENTS.md` predate BLE removal and are stale — don't trust their BLE/Waveshare content.

## Recent session highlights

Full per-session history (the reasoning behind gotchas #11–#15, BLE removal, Phase 2 theming, the security review, UDP discovery) moved to [doc/HISTORY.md](doc/HISTORY.md). Read the relevant entry before reworking any of those areas.

## Daemon / host side

`daemon/claude_usage_daemon.py` reads the Claude OAuth token, polls the Anthropic API (and Copilot/sysinfo/vscode/env/aurora/ci/today sources), and **POSTs** each JSON payload to the device's `POST /api/payload` (`firmware/src/web_server.cpp`) — BLE was removed from the firmware (CLAUDE.md gotcha #14), so WiFi/HTTP is the sole transport now. Windows: installed as a per-user Scheduled Task via `daemon/install-windows.ps1` (see that script's own `.SYNOPSIS` for why it's a Scheduled Task and not a true Service). Linux: `systemctl --user start claude-usage-daemon` via `daemon/claude-usage-daemon.service` — the unit file's `ExecStart` is the absolute path to the script, repoint it when switching between the worktree and the main checkout.

`daemon/cloud_push.py` (optional, off unless `cloud_url` is set) feeds the remote dashboard in `cloud/` (Next.js on Vercel Hobby + Upstash Redis): once a minute it GETs the device's `/api/state`, keeps a field-level allowlist (never the token/IPs; weather/ci/vscode are opt-in via `cloud_sections`), HMAC-signs it with `cloud_secret` and POSTs to `/api/ingest`. Outbound-only and read-only -- the cloud has no path back to the device. The page is GitHub-OAuth-gated to one numeric GitHub id. `tools/fixtures/cloud_snapshot.json` is the shared contract: `tools/tests/test_cloud_push.py` pins the daemon's output to it and `cloud/test/schema.test.ts` validates it against the zod schema. Setup and security model: `cloud/README.md`.

`daemon/codex_usage.py` runs a managed local Codex app-server and reads `account/rateLimits/read` every minute, also accepting quota notifications. It uses the existing Codex sign-in and sends only normalized quota data to the device. Its task is independent of other source polling; device writes are serialized. Cached readings retain their sample time and become stale after three minutes. Optional daemon config keys `codex_path` and `codex_bucket` override executable discovery and the default quota bucket.

`daemon/claude-usage-daemon.sh` (a separate, older, Linux/macOS-only bash+`bluetoothctl` implementation, far fewer features — Claude usage only, no Copilot/sysinfo/vscode/etc.) is **retired/unmaintained** — left in the repo as a historical artifact, not touched when BLE was removed. `claude_usage_daemon.py` is the canonical daemon.

**Setup (manual, one-time, no longer daemon-driven):**

1. Provision WiFi on the device over serial/USB: `feed {"src":"wifi","ssid":"...","pass":"..."}` (see the `run` skill). There's no SoftAP/captive-portal fallback.
2. Once connected, read the IP + auth token off the device's Connectivity screen.
3. Add `device_token = <token from screen>` to `~/.config/claude-usage-monitor/config`. (Optional: `device_host = <ip-or-hostname>` overrides mDNS resolution, for setups where OS-level `.local` resolution isn't available — see below.)

**Discovery & resilience:**

- `resolve_device_ip()` is a 2-tier fallback. Tier 1: `getaddrinfo()` against `device_host` (if set) or `clawdmeter.local` — the OS resolver (`asyncio`'s `getaddrinfo`, which delegates to the platform DNS client), not a Python mDNS library; `zeroconf`'s `AsyncZeroconf` (as of 0.151.3) has no direct hostname-resolve call, only service-type browsing, so it would've added a dependency for no benefit. Windows 10+ and macOS resolve `.local` names natively; Linux needs `nss-mdns`/avahi (common on desktop distros, not guaranteed on minimal ones). Tier 2, only reached if tier 1 fails: `_discover_broadcast_sync()` sends a UDP broadcast on port 42424 (`DISCOVERY_REQUEST = b"CLAWDMETER_DISCOVER_V1"`) and waits up to `DISCOVERY_TIMEOUT=2.0`s for a device matching `DISCOVERY_REPLY = b"CLAWDMETER_HELLO_V1"` to answer (`firmware/src/discovery.{h,cpp}` is the device-side responder) — this self-heals a drifted/changed IP without any manual reconfiguration, so **`device_host` is now an optional pin/override, not a requirement**: it's still useful on networks where UDP broadcast is filtered (some corporate/guest VLANs) or to skip the discovery round-trip entirely, but a fresh install with no `device_host` set at all will still find the device via mDNS first, UDP broadcast second. `tools/discover_device.py` is a standalone CLI wrapping the same tier-2 protocol (`--timeout`/`--port` flags) for manual troubleshooting independent of the daemon.
- Caches the resolved IP at `~/.config/claude-usage-monitor/device-ip`. On failed probe/4 consecutive write failures, the cache is dropped so the next attempt re-resolves (re-running both tiers, so a changed IP is picked up automatically on the next successful cycle).
- `POLL_INTERVAL=60`, `TICK=5`. Inner loop wakes every 5s; polls Anthropic when 60s elapsed. (The old "ESP fires a refresh request over BLE notify" mechanism has no HTTP-push equivalent and was dropped — the long-press gesture that triggered it now just flashes feedback, see `main.cpp`'s button handler.)
- `POST /api/payload` requires an `X-Auth-Token` header matching the device's token (`wifi_get_token()` in `wifi_net.h`) — the only mutating route. `GET /api/state`/`GET /` stay open/unauthenticated by design, and deliberately never expose the token (or an unauthenticated read route would leak the credential that's supposed to gate the write route).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
