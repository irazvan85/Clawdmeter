#include "wifi_net.h"
#include <WiFi.h>
#include <Preferences.h>
#include <string.h>

#define WIFI_NVS_NS         "wifi"
#define CONNECT_TIMEOUT_MS  15000UL
#define RETRY_BACKOFF_MS    30000UL
#define TOKEN_LEN           8

static wifi_state_t state        = WIFI_STATE_OFF;
static char         ssid_buf[33] = "";
static char         pass_buf[65] = "";
static char         token_buf[TOKEN_LEN + 1] = "";
static uint32_t     connect_start_ms = 0;
static uint32_t     next_retry_ms    = 0;
static bool         have_creds       = false;

static void load_credentials(void) {
    Preferences p;
    // Read-write, not read-only: opening a namespace that has never been
    // created before in read-only mode crashes on this esp32-arduino version
    // (assert failed: xQueueSemaphoreTake, right after the expected nvs_open
    // NOT_FOUND) -- read-write auto-creates the namespace instead of hitting
    // that path. "wifi" is empty on a fresh flash, so this always applies on
    // first boot after upgrading to this firmware.
    if (!p.begin(WIFI_NVS_NS, false)) return;
    String s  = p.getString("ssid", "");
    String pw = p.getString("pass", "");
    String t  = p.getString("token", "");
    p.end();
    if (s.length() > 0) {
        strlcpy(ssid_buf, s.c_str(), sizeof(ssid_buf));
        strlcpy(pass_buf, pw.c_str(), sizeof(pass_buf));
        have_creds = true;
    }
    if (t.length() == TOKEN_LEN) {
        strlcpy(token_buf, t.c_str(), sizeof(token_buf));
    }
}

static void save_credentials(const char* ssid, const char* pass) {
    Preferences p;
    if (!p.begin(WIFI_NVS_NS, false)) return;
    p.putString("ssid", ssid);
    p.putString("pass", pass);
    p.end();
}

// esp_wifi_start() needs a sizeable contiguous allocation for its internal
// buffers. If it fails with ESP_ERR_NO_MEM, the WiFi driver task has been
// observed to spin without yielding instead of failing cleanly, starving
// IDLE0 and tripping the task watchdog -- a hard crash-reboot loop, since
// the same (already-persisted) credentials get retried on every boot. Guard
// the call instead of handling its failure: skip this attempt (and retry
// later via the normal FAILED backoff) whenever the largest free block looks
// too small, so we never actually make the risky call in an unsafe state.
// See CLAUDE.md gotcha #14 for the full incident writeup.
#define WIFI_MIN_MAX_ALLOC 90000UL
// Separate, lower bar for WiFi.begin(): the 90 KB figure above was
// calibrated to also survive *concurrent BLE traffic* landing at the same
// low-heap moment (a too-low bar once let WiFi.begin() through at ~32 KB,
// which was fine for the call itself but not enough margin for a live BLE
// GATT write minutes later -- see CLAUDE.md gotcha #14). That risk doesn't
// exist anymore: BLE was removed entirely. Re-measured post-removal:
// post-ui_init() max-alloc sits at ~82 KB, under the old 90 KB bar but with
// real margin above the ~32 KB level that used to be unsafe -- 50 KB keeps
// a comfortable margin for WebServer/ArduinoJson's own transient
// allocations without blocking WiFi from ever actually connecting.
#define WIFI_MIN_MAX_ALLOC_BEGIN 50000UL

// True once WiFi.mode(WIFI_STA) has actually run (i.e. esp_wifi_start()
// succeeded and claimed its one-time buffer allocation). Separated from
// "have_creds" because priming deliberately happens as early as possible
// (see wifi_init_early()) -- on a fresh, unfragmented heap -- while the
// actual WiFi.begin() association can happen later/repeatedly.
static bool primed = false;

static bool heap_ok_for_wifi_start(void) {
    uint32_t free_heap = ESP.getFreeHeap();
    uint32_t max_alloc  = ESP.getMaxAllocHeap();
    Serial.printf("[wifi] heap check: free=%u max_alloc=%u\n", free_heap, max_alloc);
    Serial.flush();
    return max_alloc >= WIFI_MIN_MAX_ALLOC;
}

static void prime_wifi_driver(void) {
    WiFi.mode(WIFI_STA);
    Serial.println("[wifi] WiFi.mode(WIFI_STA) returned");
    Serial.flush();
    primed = true;
}

static void start_connect(void) {
    if (!have_creds) return;
    if (!primed) {
        if (!heap_ok_for_wifi_start()) {
            Serial.println("[wifi] insufficient contiguous heap for esp_wifi_start(); deferring");
            state = WIFI_STATE_FAILED;
            next_retry_ms = millis() + RETRY_BACKOFF_MS;
            return;
        }
        prime_wifi_driver();
    }
    // Second checkpoint, same threshold as above (see WIFI_MIN_MAX_ALLOC_BEGIN's
    // comment): guards WiFi.begin() and continued operation afterward, not
    // just esp_wifi_start().
    Serial.printf("[wifi] pre-begin heap: free=%u max_alloc=%u\n", ESP.getFreeHeap(), ESP.getMaxAllocHeap());
    Serial.flush();
    if (ESP.getMaxAllocHeap() < WIFI_MIN_MAX_ALLOC_BEGIN) {
        Serial.println("[wifi] insufficient contiguous heap for WiFi.begin(); deferring");
        state = WIFI_STATE_FAILED;
        next_retry_ms = millis() + RETRY_BACKOFF_MS;
        return;
    }
    WiFi.begin(ssid_buf, pass_buf);
    Serial.println("[wifi] WiFi.begin() returned");
    Serial.flush();
    state = WIFI_STATE_CONNECTING;
    connect_start_ms = millis();
}

// Call once, BEFORE ui_init(): if credentials are already stored, this is
// the one chance to claim esp_wifi_start()'s one-time large contiguous
// allocation while the heap is still pristine, before LVGL's many small
// widget/style/canvas allocations fragment it. Measured on-device: by the
// time ui_init() has run, max contiguous free heap can drop to ~49 KB (of
// ~64 KB still nominally free) -- well under what esp_wifi_start() needs,
// which is what caused the ESP_ERR_NO_MEM crash-loop this guards against
// (CLAUDE.md gotcha #14). No-op (zero allocation) when no credentials are
// stored yet -- WiFi stays fully zero-cost until the user provisions it.
void wifi_init_early(void) {
    load_credentials();
    if (!have_creds) return;
    if (!heap_ok_for_wifi_start()) {
        // Heap was already this tight before the UI even ran -- unusual,
        // but don't force it. start_connect() (called later from wifi_init())
        // re-checks and will keep retrying via the normal backoff.
        Serial.println("[wifi] early priming skipped (heap already tight); will retry later");
        return;
    }
    prime_wifi_driver();
}

// Call once, AFTER ui_init(): starts the actual connect attempt, reusing
// the driver primed by wifi_init_early() above when possible.
void wifi_init(void) {
    if (have_creds) start_connect();
}

void wifi_tick(void) {
    switch (state) {
    case WIFI_STATE_OFF:
        break;
    case WIFI_STATE_CONNECTING:
        if (WiFi.status() == WL_CONNECTED) {
            state = WIFI_STATE_CONNECTED;
        } else if (millis() - connect_start_ms > CONNECT_TIMEOUT_MS) {
            state = WIFI_STATE_FAILED;
            next_retry_ms = millis() + RETRY_BACKOFF_MS;
        }
        break;
    case WIFI_STATE_CONNECTED:
        if (WiFi.status() != WL_CONNECTED) {
            state = WIFI_STATE_FAILED;
            next_retry_ms = millis() + RETRY_BACKOFF_MS;
        }
        break;
    case WIFI_STATE_FAILED:
        if (millis() >= next_retry_ms) start_connect();
        break;
    }
}

void wifi_set_credentials(const char* ssid, const char* pass) {
    if (strcmp(ssid, ssid_buf) == 0 && strcmp(pass, pass_buf) == 0) return;  // unchanged, no-op
    strlcpy(ssid_buf, ssid, sizeof(ssid_buf));
    strlcpy(pass_buf, pass, sizeof(pass_buf));
    have_creds = (strlen(ssid_buf) > 0);
    save_credentials(ssid_buf, pass_buf);
    if (have_creds) {
        start_connect();
    } else {
        WiFi.disconnect(true);
        state = WIFI_STATE_OFF;
    }
}

wifi_state_t wifi_get_state(void) { return state; }

String wifi_get_ip(void) {
    if (state != WIFI_STATE_CONNECTED) return "";
    return WiFi.localIP().toString();
}

// Excludes visually-ambiguous characters (0/O, 1/I) since this gets read off
// a 135px-wide screen and typed into a browser.
static const char TOKEN_CHARSET[] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

const char* wifi_get_token(void) {
    if (token_buf[0] != '\0') return token_buf;
    for (int i = 0; i < TOKEN_LEN; i++) {
        token_buf[i] = TOKEN_CHARSET[esp_random() % (sizeof(TOKEN_CHARSET) - 1)];
    }
    token_buf[TOKEN_LEN] = '\0';
    Preferences p;
    if (p.begin(WIFI_NVS_NS, false)) {
        p.putString("token", token_buf);
        p.end();
    }
    return token_buf;
}
