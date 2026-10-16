---
name: payload-contract
description: "The daemon ↔ device contract for Clawdmeter: HTTP routes, auth token, payload `src` types and keys, discovery. Use when changing daemon/claude_usage_daemon.py payloads, process_payload() in main.cpp, data.h structs, web_server.cpp routes, /api/state JSON, the X-Auth-Token check, mDNS/UDP discovery, or when debugging 'device not updating', 401s, or empty POST bodies. Replaces the old BLE contract (BLE was removed; see CLAUDE.md gotcha #14)."
---

# Daemon ↔ device contract (WiFi/HTTP)

Transport is HTTP on port 80 only. BLE is gone — ignore anything under `.github/` or `AGENTS.md` that mentions GATT/NimBLE/`ble.cpp`.

## Routes (`firmware/src/web_server.cpp`)

| Route | Auth | Body | Notes |
|---|---|---|---|
| `GET /` | open | — | gzip'd dashboard from `web_ui.h` |
| `GET /api/state` | open | — | `build_state_json()` in main.cpp. **Must never contain the token** (security_test.py asserts it). Includes `device` perf counters (perf.cpp) and `connectivity.screen`. |
| `GET /api/screenshot.bmp` | token | — | tile-streamed, top-down BMP (gotcha #15). Token-gated because it can render the Connectivity screen, which shows the token. |
| `POST /api/payload` | token | **JSON**, `Content-Type: application/json` required | Without that header `server.arg("plain")` is empty → 400 (the "curl -d" gotcha). |
| `GET /api/config` | open | — | theme + visibility mask |
| `POST /api/config` | token | form-encoded `theme`, `mask` | theme change replies first, restarts ~a beat later; out-of-range theme must not restart |
| `POST /api/screen` | token | form-encoded `n=<idx>` or `action=next` | wraps `ui_show_screen()`/`ui_cycle_screen()` |

Token: `wifi_get_token()` (persisted in NVS, printed by serial `token`), header `X-Auth-Token`. **Any new route** is either token-gated before its first 200 or added to `UNAUTHENTICATED_BY_DESIGN` in `tools/check_auth_gated_routes.py` with a justification — the guard (and the PostToolUse hook on `web_server.cpp`) fails otherwise.

## Payloads (`process_payload()` in main.cpp)

Routed by `src` (default `claude`). Key names are short to keep payloads small:

`claude` s sr w wr st mdl ctx ok · `copilot` pp pr pe prm prd plan en · `sysinfo` cpu ct rp ru rt dp du dt · `vscode` mm vc xe ec le · `act` st n · `ci` state wf br age rev chg dty ah bh cf · `sum` am tk usd cm cp · `env` ts tz tp th tl tc tn · `aurora` ts pct kp kpmax cloud night · `status` state · `wifi` ssid pass (serial provisioning only)

Source of truth is the code; `tools/fixtures/payloads.json` mirrors it and `tools/tests/test_payload_contract.py` fails if they diverge in either direction. Changing a key: update firmware + daemon + fixture in the same commit. Strings must be ASCII (device fonts) — daemon uses `_ascii()`.

## Daemon rules (`daemon/claude_usage_daemon.py`)

- `remember_payload()`/`load_last_payloads()` must keep excluding `status`, `act`, **`wifi`** (a cached wifi payload once sat in plaintext and would have been replayed) — covered by `tools/tests/test_daemon.py`.
- Device resolution: `device_host` config → `clawdmeter.local` via OS resolver → UDP broadcast on 42424 (`CLAWDMETER_DISCOVER_V1` → `CLAWDMETER_HELLO_V1`, IP taken from the packet source, never the payload). Cached IP is dropped after a failed probe / 4 write failures.
- WiFi provisioning is manual over serial (`feed {"src":"wifi",...}`), never daemon-driven.

## Testing

- Host: `python tools/preflight.py --only tests static`.
- Device: `tools/security_test.py --host <ip> --token <t>` (auth regressions, malformed JSON, oversized bodies, mask=0 safety; `--allow-restart` for the theme check). `tools/perf_check.py --host` for latency + live heap.
- Smoke: `curl -X POST -H "Content-Type: application/json" -H "X-Auth-Token: <t>" -d '{"src":"status","state":"ok"}' http://clawdmeter.local/api/payload`
