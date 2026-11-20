#pragma once
#include <stdint.h>
#include <ArduinoJson.h>

// Why did the device restart, and what was it doing just before?
//
// esp_reset_reason() only says *how* this boot started. This module also
// remembers the *previous* run: its uptime, the screen on display, and its
// heap low-water marks -- enough to tell "heap ran out on screen X" from
// "something pulled EN / the 5V rail dipped".
//
// Two copies of the previous run's record:
//   - RTC_NOINIT memory, refreshed every second. Survives panic, watchdog,
//     software and brownout resets, so those get an exact final snapshot.
//   - NVS (namespace "rst"), written at 30 s, 120 s, then every 5 min (flash
//     wear: ~290 small writes/day). The fallback for a real power-on/EN
//     reset, which wipes RTC memory -- so its numbers can be up to 5 min old.
// Each record carries its boot number, so a record left over from an older
// boot is never reported as the previous run's.
//
// Read via the serial `reset` command and GET /api/state's device.last_reset.

void reset_info_init(void);   // once, early in setup(), after Serial.begin()
void reset_info_tick(void);   // every loop(); does its work once a second
void reset_info_print(void);  // serial `reset` command
void reset_info_to_json(JsonObject obj);
