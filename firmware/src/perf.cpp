#include "perf.h"
#include <Arduino.h>
#include <esp_system.h>

static uint32_t loop_t0, lv_t0;
static uint32_t loop_count;
static uint64_t loop_sum_us;
static uint32_t loop_max_us;
static uint32_t lv_max_us;
static uint32_t window_start_ms;
static uint32_t min_max_alloc = UINT32_MAX;   // worst largest-free-block seen this window

void perf_loop_begin(void) { loop_t0 = micros(); }

void perf_loop_end(void) {
    uint32_t dt = micros() - loop_t0;
    loop_count++;
    loop_sum_us += dt;
    if (dt > loop_max_us) loop_max_us = dt;
    // Sampling getMaxAllocHeap() walks the heap's free list -- cheap, but
    // not free, so only do it every 64th loop (~3 Hz at the 5 ms loop delay).
    if ((loop_count & 63) == 0) {
        uint32_t ma = ESP.getMaxAllocHeap();
        if (ma < min_max_alloc) min_max_alloc = ma;
    }
}

void perf_lv_begin(void) { lv_t0 = micros(); }

void perf_lv_end(void) {
    uint32_t dt = micros() - lv_t0;
    if (dt > lv_max_us) lv_max_us = dt;
}

void perf_reset(void) {
    loop_count = 0;
    loop_sum_us = 0;
    loop_max_us = 0;
    lv_max_us = 0;
    min_max_alloc = UINT32_MAX;
    window_start_ms = millis();
}

void perf_to_json(JsonObject obj) {
    uint32_t ma = ESP.getMaxAllocHeap();
    obj["uptime_s"]       = millis() / 1000;
    obj["reset_reason"]   = (int)esp_reset_reason();
    obj["heap_free"]      = ESP.getFreeHeap();
    obj["heap_min_free"]  = ESP.getMinFreeHeap();
    obj["max_alloc"]      = ma;
    obj["max_alloc_min"]  = (min_max_alloc == UINT32_MAX) ? ma : min_max_alloc;
    obj["loops"]          = loop_count;
    obj["loop_avg_us"]    = loop_count ? (uint32_t)(loop_sum_us / loop_count) : 0;
    obj["loop_max_us"]    = loop_max_us;
    obj["lv_max_us"]      = lv_max_us;
    obj["window_s"]       = (millis() - window_start_ms) / 1000;
}
