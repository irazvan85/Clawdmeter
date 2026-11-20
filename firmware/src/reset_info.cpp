#include "reset_info.h"
#include "ui.h"
#include <Arduino.h>
#include <Preferences.h>
#include <esp_attr.h>
#include <esp_system.h>

namespace {

#define RI_MAGIC        0x52535431u   // "RST1"
#define RI_TICK_MS      1000
#define RI_NVS_FIRST_S  30
#define RI_NVS_SECOND_S 120
#define RI_NVS_EVERY_S  300

struct Record {
    uint32_t magic;
    uint32_t boot;            // boot number this record belongs to
    uint32_t uptime_s;
    uint32_t heap_free;       // at the moment of the snapshot
    uint32_t heap_min_free;   // since boot (ESP.getMinFreeHeap())
    uint32_t max_alloc;       // largest free block at the snapshot
    uint32_t max_alloc_min;   // worst largest-free-block seen since boot
    int32_t  screen;          // screen_t on display
    uint32_t check;           // XOR of the fields above, catches garbage
};

uint32_t checksum(const Record& r) {
    return r.magic ^ r.boot ^ r.uptime_s ^ r.heap_free ^ r.heap_min_free ^
           r.max_alloc ^ r.max_alloc_min ^ (uint32_t)r.screen ^ 0xA5A5A5A5u;
}

// Survives every reset except power-on/EN (and is garbage after one, which
// magic + checksum + boot number reject).
RTC_NOINIT_ATTR Record rtc_rec;

uint32_t boot_no       = 0;      // this boot
int      reason        = 0;      // esp_reset_reason_t of this boot
Record   prev          = {};     // previous run, if found
const char* prev_src   = "none"; // "rtc" | "nvs" | "none"
bool     have_prev     = false;
uint32_t max_alloc_min = UINT32_MAX;
uint32_t last_tick_ms  = 0;
uint32_t next_nvs_s    = RI_NVS_FIRST_S;

bool valid_for(const Record& r, uint32_t boot) {
    return r.magic == RI_MAGIC && r.check == checksum(r) && r.boot == boot;
}

const char* reason_name(int r) {
    switch (r) {
    case 1:  return "poweron";    // also the EN pin (USB-serial DTR/RTS, button)
    case 2:  return "ext";
    case 3:  return "sw";         // ESP.restart() -- e.g. a theme change
    case 4:  return "panic";
    case 5:  return "int_wdt";
    case 6:  return "task_wdt";
    case 7:  return "wdt";
    case 8:  return "deepsleep";
    case 9:  return "brownout";
    case 10: return "sdio";
    default: return "unknown";
    }
}

void save_nvs(const Record& r) {
    Preferences p;
    if (!p.begin("rst", false)) return;   // read-write: gotcha #11
    p.putBytes("last", &r, sizeof(r));
    p.end();
}

Record snapshot(void) {
    Record r;
    r.magic         = RI_MAGIC;
    r.boot          = boot_no;
    r.uptime_s      = millis() / 1000;
    r.heap_free     = ESP.getFreeHeap();
    r.heap_min_free = ESP.getMinFreeHeap();
    r.max_alloc     = ESP.getMaxAllocHeap();
    if (r.max_alloc < max_alloc_min) max_alloc_min = r.max_alloc;
    r.max_alloc_min = max_alloc_min;
    r.screen        = (int32_t)ui_get_current_screen();
    r.check         = checksum(r);
    return r;
}

}  // namespace

void reset_info_init(void) {
    reason = (int)esp_reset_reason();

    // Read-write open: first-ever access to a namespace crashes read-only
    // (CLAUDE.md gotcha #11).
    Record nvs_rec = {};
    Preferences p;
    if (p.begin("rst", false)) {
        boot_no = p.getUInt("boots", 0) + 1;
        p.putUInt("boots", boot_no);
        if (p.getBytesLength("last") == sizeof(nvs_rec)) p.getBytes("last", &nvs_rec, sizeof(nvs_rec));
        p.end();
    }

    // RTC is exact (last second before the reset); NVS is the fallback.
    if (valid_for(rtc_rec, boot_no - 1))      { prev = rtc_rec; prev_src = "rtc"; have_prev = true; }
    else if (valid_for(nvs_rec, boot_no - 1)) { prev = nvs_rec; prev_src = "nvs"; have_prev = true; }
    rtc_rec.magic = 0;   // this boot's first tick writes a fresh record

    reset_info_print();
}

void reset_info_tick(void) {
    uint32_t now = millis();
    if (last_tick_ms != 0 && now - last_tick_ms < RI_TICK_MS) return;
    last_tick_ms = now;

    Record r = snapshot();
    rtc_rec = r;
    if (r.uptime_s >= next_nvs_s) {
        save_nvs(r);
        next_nvs_s = next_nvs_s < RI_NVS_SECOND_S ? RI_NVS_SECOND_S
                                                  : r.uptime_s + RI_NVS_EVERY_S;
    }
}

void reset_info_print(void) {
    Serial.printf("reset: boot #%lu, reason=%d (%s)\n",
                  (unsigned long)boot_no, reason, reason_name(reason));
    if (!have_prev) {
        Serial.println("reset: no record of the previous run");
        return;
    }
    Serial.printf("reset: previous run (from %s%s): up %lus, screen %ld, heap free %lu "
                  "(min %lu), max block %lu (min %lu)\n",
                  prev_src, strcmp(prev_src, "nvs") == 0 ? ", up to 5 min stale" : "",
                  (unsigned long)prev.uptime_s, (long)prev.screen,
                  (unsigned long)prev.heap_free, (unsigned long)prev.heap_min_free,
                  (unsigned long)prev.max_alloc, (unsigned long)prev.max_alloc_min);
}

void reset_info_to_json(JsonObject obj) {
    obj["boot"]        = boot_no;
    obj["reason"]      = reason;
    obj["reason_name"] = reason_name(reason);
    obj["prev_src"]    = prev_src;
    if (!have_prev) return;
    JsonObject pr = obj["prev"].to<JsonObject>();
    pr["uptime_s"]      = prev.uptime_s;
    pr["screen"]        = prev.screen;
    pr["heap_free"]     = prev.heap_free;
    pr["heap_min_free"] = prev.heap_min_free;
    pr["max_alloc"]     = prev.max_alloc;
    pr["max_alloc_min"] = prev.max_alloc_min;
}
