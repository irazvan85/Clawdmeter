# Project context

ESP32 firmware for a desk-side Claude Code usage monitor on an **ideaspark ESP32 1.14" ST7789** board (135×240 IPS SPI LCD). Connects to a host daemon over BLE; daemon polls Anthropic API for usage data.

This file is for future Claude Code sessions to bootstrap quickly. Read this first.

## Hardware (critical pins)

- MCU: **ESP32-WROOM-32** (240 MHz, 320 KB SRAM, 4 MB Flash, **no PSRAM**, BLE 4.2)
- Display: **ST7789** 135×240 IPS via SPI — MOSI=23, SCLK=18, CS=15, DC=2, RST=4, BLK=32
- Touch: **none**
- PMU: **none** (no battery, no AXP)
- IMU: **none** (no auto-rotation; rotation fixed at 0)
- USB-serial: CH340 on **COM13** (Windows)
- Buttons: GPIO 0 (back/left button only). GPIO 18 is LCD SCLK — **cannot be used as button**.

## Architecture

```text
main.cpp        — setup(), loop(), BTN_BACK (GPIO0) polling, serial commands (screenshot, etc.)
display_cfg.h   — pin defines (ST7789 SPI), LCD_WIDTH=135, LCD_HEIGHT=240, extern bus/gfx objects
ui.{h,cpp}      — 4-screen UI (splash, usage, copilot, bluetooth); redesigned for 135×240
splash.{h,cpp}  — 20×20 pixel-art animation engine; 6× upscale (120×120) on splash, 4× (80×80) on Copilot screen
imu.{h,cpp}     — stub: imu_get_rotation() always returns 0
power.{h,cpp}   — stub: battery=-1, charging=false, pwr_pressed=false
ble.{h,cpp}     — NimBLE peripheral: custom data service + HID keyboard (unchanged)
data.h          — UsageData struct (unchanged)
icons.h         — icon arrays (RGB565)
logo.h          — 80×80 RGB565 logo (hidden at runtime — too wide for 135px)
font_*.c        — LVGL 9 bitmap fonts in use: Tiempos 34, Styrene 24/16/14/12, Mono 18
splash_animations.h — generated, do not hand-edit
```

## Build / flash (Windows)

```powershell
# Build
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware

# Flash
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d firmware -t upload --upload-port COM13
```

Device is on COM13 via CH340 USB-serial. Hold BOOT (GPIO0) while pressing EN if the chip doesn't enter download mode automatically (rarely needed).

## QA your own UI changes — don't ask the user

The firmware ships a `screenshot` serial command that dumps the LVGL framebuffer over the serial port. `./screenshot.sh out.png COM13` (or the Windows equivalent) captures a 135×240 PNG. **Use this on every UI iteration** — read the PNG, verify visually, iterate.

The boot screen is `SCREEN_SPLASH` and only advances on a physical button press. To screenshot a different screen without asking the user to press a button, **temporarily change the default boot screen** in `main.cpp` (search for `ui_show_screen(SCREEN_SPLASH);`) to `SCREEN_USAGE` / `SCREEN_BLUETOOTH`, iterate, then revert before committing.

## Critical gotchas

1. **pioarduino platform required.** GFX Library for Arduino 1.6.x needs Arduino Core 3.x (`esp32-hal-periman.h`), which standard `espressif32` 7.x does NOT provide. We use `pioarduino/platform-espressif32` (stable zip URL in platformio.ini). Standard `espressif32` gives Core 2.x → compile failure.
2. **No PSRAM.** ESP32-WROOM-32 has no SPIRAM. All `heap_caps_malloc(…MALLOC_CAP_SPIRAM)` must be plain `malloc()`. LVGL partial render buffers are 135×40×2 = 10,800 bytes each — fits comfortably in SRAM.
3. **ST7789 col/row offsets.** The 1.14" 135×240 panel needs `col_offset=52, row_offset=40` in `Arduino_ST7789` constructor or the image is shifted off-screen.
4. **GPIO 18 = LCD SCLK.** Cannot be used for any other purpose (was BTN_FWD on the old board). BTN_FWD/right-button is permanently disabled.
5. **Flash tight at 90%.** The default partition scheme gives 1.31 MB app space. Current build uses ~90%. Do not add large new font files or feature libraries without checking size. `pio run` reports flash usage after every build.
6. **NimBLE-Arduino 2.5.0 deprecation warning.** `svc->start()` in `ble.cpp:154` emits a `-Wdeprecated-declarations` warning. This is harmless — the call is a no-op that still compiles and links cleanly. Do not remove it without testing BLE.
7. **LVGL 9 font patching.** `lv_font_conv` outputs LVGL 8 format. Must remove `#if LVGL_VERSION_MAJOR >= 8` guards, drop `.cache` field, add `.release_glyph`, `.kerning`, `.static_bitmap`, `.fallback`, `.user_data`. Without patching, fonts render invisible.
8. **LVGL RGB565A8 is planar.** `w*h` RGB565 pixels followed by `w*h` alpha bytes; `data_size = w*h*3`, `stride = w*2`. Use `init_icon_dsc_rgb565a8()` for icons that overlap non-uniform backgrounds. Lucide source PNGs are black-on-transparent — converter must tint to white. See `tools/png_to_lvgl.js`.

## Icons

`tools/png_to_lvgl.js <input.png> <symbol> [W_MACRO] [H_MACRO] [--tint=RRGGBB | --no-tint]` converts an alpha PNG to RGB565A8. Default tint is white (`0xFFFFFF`) — necessary for Lucide PNGs. Splice output into `firmware/src/icons.h` and use `init_icon_dsc_rgb565a8()` in ui.cpp.

## Splash animations

15 × 20×20 pixel-art animations. 13 sourced from [claudepix.vercel.app](https://claudepix.vercel.app) (splash screen). 2 are manually authored Copilot mascot animations (`copilot_idle.json`, `copilot_thinking.json`). Pipeline:

```bash
node tools/scrape_claudepix.js  # → tools/claudepix_data/*.json (claudepix only)
node tools/convert_to_c.js      # → firmware/src/splash_animations.h (all 15)
```

Each animation has a per-animation palette (up to 10 colors). Cell values index it. Splash screen renders at 6× scale (120×120). Copilot screen renders at 4× scale (80×80) and cycles between `copilot_idle` (10s) and `copilot_thinking` (5s). Do not hand-edit `splash_animations.h` — regenerate with `convert_to_c.js`.

## Recent session highlights

- Originally targeted Waveshare ESP32-S3-Touch-AMOLED-2.16 (480×480, CO5300, PSRAM, IMU, touch, PMU). See git history for that version.
- **Ported to ideaspark ESP32 1.14" ST7789** (135×240, no PSRAM, no IMU, no touch, no PMU). Full hardware swap: SPI display driver, stub power/IMU, complete UI layout redesign for 135×240, LVGL buffers in SRAM.
- pioarduino platform retained (needed by GFX Library 1.6.x for `esp32-hal-periman.h`); switched board from `esp32s3box` → `esp32dev`.
- Flash usage is tight (~90%); do not add large assets without checking.
- **Added Copilot screen** (`SCREEN_COPILOT`) — VS Code-style premium-request usage panel: big colored `%` label (`lbl_copilot_pct`, `font_styrene_24`, colored by `pct_color()`), fraction right-aligned, progress bar (green/amber/red), reset date. Panel height 90px.
- **Copilot animations**: `COPILOT_CELL=4` → 80×80 canvas. Cycles idle↔thinking: `COPILOT_IDLE_HOLD_MS=10000`, `COPILOT_THINK_HOLD_MS=5000`. Both animation indices looked up by name in `splash_copilot_init()`.
- **`copilot_thinking.json`** manually authored: 4 frames, squinting eyes + light-blue thought dots (upper-right). Not from claudepix scraper — keep in `tools/claudepix_data/` alongside `copilot_idle.json`.
- **`data.h` `CopilotData`**: fields `premium_pct`, `premium_remaining`, `premium_total`, `premium_reset_mins`, `premium_reset_str[24]`, `plan[20]`, `enabled`, `valid`.
- **`daemon/claude_usage_daemon.py`**: plan name mapping (`individual`→`Pro` etc.), `prd` formatted reset date field.

## Daemon / host side

Bash daemon (`daemon/claude-usage-daemon.sh`) reads OAuth token, polls Anthropic API, sends JSON over BLE GATT. Run with `systemctl --user start claude-usage-daemon`. The unit file's `ExecStart` is the absolute path to the script — repoint it when switching between the worktree and the main checkout.

**Discovery & resilience:**

- Connects by name (`"Claude Controller"`) on first run, caches resolved MAC at `~/.config/claude-usage-monitor/ble-address`. ESP32 BLE addresses are factory-burned per-chip, so swapping any board invalidates the cache.
- On connect failure: cache is dropped AND device is removed from bluez (`bluetoothctl remove`) so the next scan won't re-pick a dead MAC. Multi-candidate scans pick `head -1` and let the failure cycle converge.
- `POLL_INTERVAL=60`, `TICK=5`. Inner loop wakes every 5s to detect disconnects fast; polls Anthropic when 60s elapsed OR when ESP fires a refresh request.

**GATT characteristics on service `4c41555a-...0001`:**

- `...0002` RX — daemon writes JSON usage payload here.
- `...0003` TX — firmware notifies ack/nack (daemon doesn't subscribe).
- `...0004` REQ — firmware fires `0x01` notify in `onSubscribe` if `has_received_data` is false. Daemon subscribes via `setsid bash -c "stdbuf -oL dbus-monitor … | awk …"`; awk drops a flag file the inner loop picks up. See the `feedback_dbus_monitor_pipe` memory for the three subtle gotchas (pipe buffering, busctl-exits race, `wait` blocking on pipeline jobs).
