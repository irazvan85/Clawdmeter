#pragma once
#include <stdint.h>
#include <ArduinoJson.h>

// Runtime performance/resource counters -- the runtime counterpart to
// tools/check_static_mem.py, which only sees link-time (static) usage and
// would never have caught CLAUDE.md gotcha #14 (runtime heap exhaustion).
//
// Tracks loop() iteration time, lv_timer_handler() time (the call that hung
// in gotcha #13), and heap free / low-water mark / largest free block.
// Window stats (avg/max) reset on every perf_reset(); the heap low-water mark
// (ESP.getMinFreeHeap()) is since-boot and can't be reset.
//
// Read via the serial `perf` command (one JSON line, `perf reset` clears the
// window) or GET /api/state's "device" object -- tools/perf_check.py drives
// both. Costs two micros() calls per loop and ~40 bytes of RAM.

void perf_loop_begin(void);
void perf_loop_end(void);
void perf_lv_begin(void);
void perf_lv_end(void);
void perf_reset(void);
void perf_to_json(JsonObject obj);
