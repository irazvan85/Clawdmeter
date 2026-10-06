#include "device_config.h"
#include <Preferences.h>

#define CFG_NVS_NS "cfg"

theme_t g_theme;

static const theme_t THEME_PRESETS[THEME_PRESET_COUNT] = {
    // 0: Default -- today's exact colors (theme.h's original literals).
    { 0x000000, 0x1f1f1e, 0xfaf9f5, 0xb0aea5, 0xd97757, 0x2a2a28 },
    // 1: Slate -- cooler panel, blue accent.
    { 0x000000, 0x22262b, 0xf5f6f8, 0x9aa3ad, 0x5b8dd6, 0x2c3138 },
    // 2: Amber -- warm panel, gold accent.
    { 0x000000, 0x241f1a, 0xf7f1e8, 0xb3a794, 0xd9a33f, 0x2e2620 },
};

// Mirrors ui.cpp's CYCLE_ORDER[] exactly -- bit i here corresponds to
// CYCLE_ORDER[i] there. Keep the two in sync (same requirement ui.cpp
// documents next to its own copy); a screen not in this list (SCREEN_SPLASH)
// is always reachable and has no bit at all.
static const screen_t CFG_SCREEN_ORDER[] = {
    SCREEN_CLOCK, SCREEN_AURORA, SCREEN_SENSOR, SCREEN_SENSOR_GRAPH, SCREEN_USAGE,
    SCREEN_COPILOT, SCREEN_SYSINFO, SCREEN_VSCODE, SCREEN_BLUETOOTH,
    SCREEN_CI, SCREEN_TODAY,
};
#define CFG_SCREEN_COUNT (sizeof(CFG_SCREEN_ORDER) / sizeof(CFG_SCREEN_ORDER[0]))

#define CLOCK_BIT (1u << 0)   // CFG_SCREEN_ORDER[0] == SCREEN_CLOCK
#define CONN_BIT  (1u << 8)   // CFG_SCREEN_ORDER[8] == SCREEN_BLUETOOTH
#define DEFAULT_MASK ((1u << CFG_SCREEN_COUNT) - 1)  // all bits on

static uint8_t  theme_idx     = 0;
static uint16_t visible_mask  = DEFAULT_MASK;

static uint16_t force_required_bits(uint16_t mask) {
    return mask | CLOCK_BIT | CONN_BIT;
}

void device_config_init(void) {
    Preferences p;
    // Read-write, not read-only: opening a namespace that has never been
    // created before in read-only mode crashes on this esp32-arduino version
    // (see CLAUDE.md gotcha #11, and wifi_net.cpp's load_credentials() for
    // the same pattern) -- read-write auto-creates the namespace instead.
    if (p.begin(CFG_NVS_NS, false)) {
        theme_idx    = (uint8_t)p.getUChar("theme", 0);
        visible_mask = p.getUShort("vismask", DEFAULT_MASK);
        p.end();
    }
    if (theme_idx >= THEME_PRESET_COUNT) theme_idx = 0;
    // Force-OR here too, not just in the setter -- protects against a
    // stale/corrupt/pre-Phase-2 NVS blob leaving Clock or Connectivity
    // unreachable. See ui.cpp's ui_cycle_screen() for why an all-disabled
    // mask would otherwise be a watchdog-reset reboot loop.
    visible_mask = force_required_bits(visible_mask);
    g_theme = THEME_PRESETS[theme_idx];
}

uint8_t device_config_get_theme(void) { return theme_idx; }

void device_config_set_theme(uint8_t idx) {
    if (idx >= THEME_PRESET_COUNT) return;
    theme_idx = idx;
    Preferences p;
    if (p.begin(CFG_NVS_NS, false)) {
        p.putUChar("theme", theme_idx);
        p.end();
    }
}

uint16_t device_config_get_visible_mask(void) { return visible_mask; }

void device_config_set_visible_mask(uint16_t mask) {
    visible_mask = force_required_bits(mask & DEFAULT_MASK);
    Preferences p;
    if (p.begin(CFG_NVS_NS, false)) {
        p.putUShort("vismask", visible_mask);
        p.end();
    }
}

bool device_config_screen_enabled(screen_t s) {
    for (unsigned i = 0; i < CFG_SCREEN_COUNT; i++) {
        if (CFG_SCREEN_ORDER[i] == s) return (visible_mask & (1u << i)) != 0;
    }
    return true;  // not in the cycle list (e.g. SCREEN_SPLASH) -- always on
}
