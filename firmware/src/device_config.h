#pragma once
#include <stdint.h>
#include "ui.h"

// Web-configurable device settings (Phase 2: theme + screen visibility).
// NVS-backed, namespace "cfg" -- see device_config.cpp for the read-write-open
// rationale (CLAUDE.md gotcha #11).

typedef struct {
    uint32_t bg, panel, text, dim, accent, bar_bg;
} theme_t;

// Live theme values -- theme.h's THEME_* macros read this directly, so a
// device_config_set_theme() + restart is all that's needed to re-skin the UI
// with zero call-site changes anywhere else.
extern theme_t g_theme;

#define THEME_PRESET_COUNT 3

// Loads persisted theme/visibility from NVS (creating the namespace with
// sane defaults on first-ever boot) and applies the theme to g_theme. Call
// once, BEFORE ui_init() -- same ordering constraint as wifi_init_early(),
// see main.cpp's setup().
void device_config_init(void);

uint8_t  device_config_get_theme(void);
// Persists; does NOT itself apply to g_theme or restart -- caller (the
// POST /api/config handler) is responsible for triggering a restart so the
// new theme takes effect (LVGL has no live-restyle hook).
void     device_config_set_theme(uint8_t idx);

uint16_t device_config_get_visible_mask(void);
// Persists. Force-ORs in the Clock and Connectivity bits before saving --
// those two screens must never become unreachable (Clock is the fallback
// destination if nothing else is enabled; Connectivity is the only on-device
// display of the WiFi IP/auth token). Applies live -- no restart needed.
void     device_config_set_visible_mask(uint16_t mask);

// True if `s` is either not part of the navigable cycle at all (e.g.
// SCREEN_SPLASH -- always reachable, never user-hideable) or its bit is set
// in the current visibility mask. Used only by navigation (ui_cycle_screen(),
// refresh_screen_dots()) -- never by screen_is_populated()'s null-container
// guard, which is a different, unrelated concern.
bool device_config_screen_enabled(screen_t s);
