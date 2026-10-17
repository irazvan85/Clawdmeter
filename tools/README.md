# Splash animation tools

Two-step pipeline for getting third-party 20×20 pixel animations onto the device.

## 1. Scrape

```bash
node scrape_claudepix.js
```

Fetches the manifest from `claudepix.vercel.app/app.js`, then each animation's
HTML file, evaluates the embedded JS in a Node VM context (loading the same
`creature-engine.js` the site uses), and writes resolved frame data to
`tools/claudepix_data/*.json`.

Each output file looks like:
```json
{
  "filename": "idle_breathe.html",
  "name": "idle breathe",
  "category": "Idle",
  "description": "...",
  "frame_count": 17,
  "frames": [{ "hold": 500, "grid": [[0,0,...],[0,1,1,...],...] }, ...]
}
```

Override URL or output dir with `--base` and `--out`.

## 2. Convert to C

```bash
node convert_to_c.js
```

Reads `tools/claudepix_data/*.json` and emits a single
`firmware/src/splash_animations.h` with:
- `splash_<ident>_frames[N][400]` — per-frame cell codes (0 = empty, 1 = body, 2 = eye)
- `splash_<ident>_holds[N]` — per-frame hold time in ms
- `splash_anims[]` — master table with name, category, frame count, pointers
- `SPLASH_ANIM_COUNT`

The firmware (`splash.cpp`) consumes this header to render and animate.

## Re-running

The scraper is idempotent — re-run any time the source library updates. The
converter overwrites the header. Rebuild firmware after running both.

## License note

The scraper hits a public site without a stated license. Confirm reuse is
appropriate for your case before redistributing the output.

# Pre-flash gates, resource report, perf check

| Script | What | Needs |
|---|---|---|
| `preflight.py` | Runs everything below that doesn't need a device: `tests/` (unittest), `check_consistency.py`, `check_auth_gated_routes.py`, `check_web_ui_xss.py`, `pio run`, `resource_report.py`. PASS/FAIL table, exit 1 on failure. `--no-build`, `--only <stage>`. | stdlib (+ PlatformIO for the build) |
| `resource_report.py` | App partition / static DRAM / IRAM budgets, deltas vs `resource_baseline.json`, largest DRAM + flash symbols. `--update-baseline` after intentional growth. | built ELF |
| `check_consistency.py` | Hand-synced tables: `screen_t` ↔ `CYCLE_ORDER` ↔ `CFG_SCREEN_ORDER` ↔ web UI lists, `web_ui.h` freshness, splash `_index.json`. | stdlib |
| `perf_check.py` | On-device: `--serial COM13` (cold boot, every screen's worst LVGL pass, heap low-water, WiFi state) and/or `--host IP --token T` (HTTP latency, live heap). | pyserial / httpx |
| `fixtures/payloads.json` | One valid payload per `src`; kept in sync with `process_payload()` by `tests/test_payload_contract.py`. | — |

`firmware/platformio.ini` runs `resource_report.py --quiet` after every build and `preflight.py --no-build` before every upload (upload aborts on failure; `CLAWDMETER_SKIP_PREFLIGHT=1` overrides). Full workflow: the `preflight` skill in `.claude/skills/`.
