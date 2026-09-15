#pragma once
#include <Arduino.h>

// WiFi station connectivity — the sole transport (BLE was removed, see
// CLAUDE.md gotcha #14). Credentials are provisioned as a one-time manual
// step over the serial `feed {"src":"wifi",...}` command (see main.cpp's
// process_payload()) and persisted in NVS (Preferences, namespace "wifi")
// — there is no captive portal / AP-mode fallback.

enum wifi_state_t {
    WIFI_STATE_OFF,         // no credentials stored yet
    WIFI_STATE_CONNECTING,
    WIFI_STATE_CONNECTED,
    WIFI_STATE_FAILED,      // last connect attempt timed out; will retry
};

// Call once from setup(), BEFORE ui_init(): loads creds from NVS and, if
// present, primes the WiFi driver's one-time large heap allocation while
// the heap is still unfragmented (see the .cpp for why this has to happen
// this early). No-op if no credentials are stored yet.
void wifi_init_early(void);
void wifi_init(void);          // call once from setup(), AFTER ui_init(); starts the connect attempt
void wifi_tick(void);          // call every loop(); non-blocking connect/retry

// Stores new credentials to NVS and (re)connects only if they actually
// changed. Called from main.cpp on a {"src":"wifi"} payload.
void wifi_set_credentials(const char* ssid, const char* pass);

wifi_state_t wifi_get_state(void);
String       wifi_get_ip(void);     // "" unless WIFI_STATE_CONNECTED

// Auth token for HTTP mutating endpoints (required by POST /api/payload,
// see web_server.cpp). Generated once (esp_random-backed) and persisted in
// the same "wifi" NVS namespace; this getter creates it on first call if
// absent. Shown on the Connectivity screen; enter it into the daemon's
// config file to authenticate its payload pushes.
const char* wifi_get_token(void);
