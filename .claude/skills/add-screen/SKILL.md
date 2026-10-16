---
name: add-screen
description: "Checklist for adding, removing, reordering, or renaming a Clawdmeter LVGL screen (screen_t / SCREEN_COUNT) or a new payload-driven screen. Use whenever touching screen_t in ui.h, CYCLE_ORDER, CFG_SCREEN_ORDER, the visibility mask, screen_is_populated(), lazy init_*_screen() builds, or the web dashboard's screen lists. Lists every table that must change together and the crash each omission caused before."
---

# Adding (or changing) a screen

A screen touches ~8 places across firmware, web UI, tooling and docs. Most compile fine when one is missed; the failure shows up as a crash on first show, a wrong checkbox, or an unreachable screen. `python tools/check_consistency.py` mechanically checks the tables marked ✓ below — run it after every step (the PostToolUse hook also runs it when you edit those files).

## Firmware

1. **`firmware/src/ui.h` — `screen_t`.** Append before `SCREEN_COUNT`. Appending keeps existing indices stable (the web dashboard's `POST /api/screen n=<idx>` and the serial `screen <n>` command use raw indices). ✓
2. **`ui.cpp` — `CYCLE_ORDER[]`** and **`device_config.cpp` — `CFG_SCREEN_ORDER[]`**: identical lists; bit *i* of the persisted visibility mask means `CYCLE_ORDER[i]`. Inserting in the middle **shifts every later bit**, so users' saved masks (NVS `cfg`) silently re-map — append at the end unless there's a reason not to. Max 16 (mask is `uint16_t`). `CLOCK_BIT`/`CONN_BIT` must still point at Clock/Connectivity. ✓
3. **Build strategy — eager or lazy?** Eager (built in `ui_init()`) only if always reachable. Anything data-gated is **lazy**: `init_X_screen()` is called from the top of `ui_update_X()` as `if (!X_has_data) init_X_screen(lv_screen_active());`. Eager-building everything ran out of heap at boot (gotcha #14) — default to lazy.
4. **Lazy ⇒ null-guard every unconditional container access.** `ui_show_screen()` hides all containers at the top of every call: add `if (X_container) lv_obj_add_flag(X_container, LV_OBJ_FLAG_HIDDEN);`. Missing this crashes the very first `ui_show_screen(SCREEN_SPLASH)` in `setup()` — and looks like a silent hang. Grep for every other place that touches all containers.
5. **`screen_is_populated()`** — add a `case` returning the `X_has_data` flag (or let it fall to `default: true` for always-present screens). Don't put visibility-mask logic here: that belongs in `screen_in_cycle()`, so the serial `screen <n>` QA command can still reach a user-hidden screen.
6. **`ui_show_screen()` switch** — show the container; if the screen uses the shared pixel-art canvas (Splash/Copilot/Aurora share one buffer, `get_shared_canvas_buf()` in `splash.cpp`), call its `splash_X_show()` to re-render — the buffer holds whichever screen drew last.
7. **Data**: new struct in `data.h`, new `strcmp(src, "x")` branch in `process_payload()` (`main.cpp`), new object in `build_state_json()` (no secrets — it's an unauthenticated route).
8. **Layout**: 135×240, fonts limited to those in `font_*.c` (ASCII only — the daemon must `_ascii()` text). Use `theme.h` `COL_*`/`THEME_*` macros, not literals (theme presets are runtime-switchable).

## Web dashboard (`tools/web_ui/index.html`)

9. **`SCREEN_NAMES[]`** — one label per `screen_t` value, enum order. ✓
10. **`CFG_SCREENS[]`** — `{ bit, label }` per `CYCLE_ORDER` bit, except Clock/Connectivity (forced on). ✓
11. Regenerate `firmware/src/web_ui.h` (`node tools/build_web_ui.js`; the PostToolUse hook does it automatically). ✓ (`web-ui-fresh`)

## Tooling, daemon, docs

12. `tools/check_consistency.py` — add the enum value → label to `LABELS`.
13. `tools/fixtures/payloads.json` — a fixture for the new `src` covering every key `process_payload()` reads (`tools/tests/test_payload_contract.py` enforces both directions).
14. `tools/perf_check.py` — append to `SCREEN_NAMES` so the sweep visits it.
15. Daemon: a `poll_X()` returning the payload dict, wired into `_poll_loop()`; ASCII-fold strings.
16. CLAUDE.md: Screens table + cycle-order sentence + the architecture block.

## Verify

`python tools/preflight.py` → flash (`run` skill) → `feed` the fixture, `screen <n>`, screenshot → `tools/perf_check.py --serial COM13` and check the new screen's worst-LVGL-pass row and the heap low-water mark didn't drop meaningfully. Also run `cycle` a dozen times and `cfg 0 0` + `cycle` (all screens hidden must not watchdog-reboot).
