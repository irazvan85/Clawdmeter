#pragma once
#include <ArduinoJson.h>
#include <stdint.h>

// Implemented in main.cpp — exposes device state to the HTTP layer
// (web_server.cpp) without moving the canonical data structs out of
// main.cpp, where they're already parsed from HTTP/serial payloads.

// Serializes everything the device currently holds (usage, copilot,
// sysinfo, vscode, env/weather, aurora, ci, today, activity, wifi status)
// into `doc` for the GET /api/state endpoint. Deliberately does NOT include
// the auth token (see wifi_get_token()) -- this route is unauthenticated by
// design, and leaking the token here would defeat POST /api/payload's gate.
void build_state_json(JsonDocument& doc);

// One captured tile: pixels covers [x1,y1]-[x2,y2] inclusive, row-major,
// RGB565. Never spans more than BUF_LINES rows (main.cpp) -- small enough
// for the callback to convert/forward without its own large allocation.
typedef void (*screenshot_tile_cb)(int x1, int y1, int x2, int y2, const uint16_t* pixels);

// Captures the current LVGL frame tile-by-tile, invoking `cb` once per tile
// as LVGL flushes it -- no full-frame buffer is ever materialized (this
// board's heap can't reliably satisfy a single ~65 KB allocation under real
// load; a single malloc() here is exactly what used to make
// GET /api/screenshot.bmp fail with "out of memory" once WiFi + an active
// daemon connection were also holding heap). Used by GET /api/screenshot.bmp;
// mirrors the serial `screenshot` command's tile-streaming, which has never
// needed a full-frame buffer either -- see main.cpp's my_flush_cb().
bool capture_screenshot_streamed(screenshot_tile_cb cb);

// Parses and routes one JSON payload exactly like the serial `feed` command
// (see main.cpp's process_payload()) -- the thin wrapper POST /api/payload
// calls to hand its request body to the same transport-agnostic dispatcher.
// Returns false if the JSON failed to parse or field validation failed.
bool device_ingest_payload(const char* raw);
