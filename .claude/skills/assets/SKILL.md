---
name: assets
description: "Generated-asset pipelines for the Clawdmeter firmware: LVGL fonts (font_*.c), icons (icons.h via png_to_lvgl.js), pixel-art animations (splash_animations.h via convert_to_c.js), and the embedded web dashboard (web_ui.h via build_web_ui.js). Use when adding/regenerating any of these, when a font renders invisible, an icon looks wrong, an animation disappeared, or the device serves an old web page."
---

# Generated assets

Every header below is **generated — never hand-edit it**. Edit the source, re-run the generator, commit both. Check size impact afterwards with `python tools/resource_report.py` (the "Largest flash symbols" table names assets directly).

| Output | Source | Generator |
|---|---|---|
| `firmware/src/web_ui.h` | `tools/web_ui/index.html` | `node tools/build_web_ui.js` |
| `firmware/src/splash_animations.h` | `tools/claudepix_data/*.json` + `_index.json` | `node tools/convert_to_c.js` |
| `firmware/src/icons.h` (spliced) | Lucide/other alpha PNG | `node tools/png_to_lvgl.js <png> <symbol> [W] [H] [--tint=RRGGBB\|--no-tint]` |
| `firmware/src/font_*.c` | TTF/OTF | `lv_font_conv` + manual LVGL-9 patch |

## Web dashboard

The PostToolUse hook regenerates `web_ui.h` automatically when `index.html` is edited; `check_consistency.py --only web-ui-fresh` verifies the header decompresses to exactly the current page (it runs in preflight, so a stale page can't be flashed). Never use `.innerHTML =` with daemon-sourced text — `tools/check_web_ui_xss.py` has an allowlist; adding to it is a reviewed decision.

## Animations

`convert_to_c.js` regenerates `splash_animations.h` from scratch and **only emits what `_index.json` lists**. Hand-authored animations (`copilot_idle`, `copilot_thinking`, `aurora_shimmer`) must be in `_index.json` — one was once silently dropped this way. `check_consistency.py --only splash-index` catches an unindexed file. 20×20 grid, ≤10-color palette per animation; rendered at 6× (splash), 3× (Copilot/Aurora). `node tools/scrape_claudepix.js` refreshes the scraped ones (check the license note in `tools/README.md`).

## Icons

Output is RGB565A8 — **planar**: `w*h` RGB565 pixels then `w*h` alpha bytes, `data_size = w*h*3`, `stride = w*2` (gotcha #8). Lucide PNGs are black-on-transparent, so keep the default white tint. Use `init_icon_dsc_rgb565a8()` in ui.cpp.

## Fonts (gotcha #7)

`lv_font_conv` emits LVGL 8 format; LVGL 9 renders it **invisible** unless patched: remove the `#if LVGL_VERSION_MAJOR >= 8` guards, drop `.cache`, add `.release_glyph`, `.kerning`, `.static_bitmap`, `.fallback`, `.user_data`. Copy an existing `font_styrene_*.c` footer as the template. Fonts are ASCII-only — keep the range minimal; a glyph range is the fastest way to burn flash.

## After any asset change

`python tools/preflight.py` (consistency + resource gates) → flash → screenshot the affected screen (`run` skill).
