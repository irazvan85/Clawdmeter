#pragma once
#include <lvgl.h>
#include "device_config.h"

// Design tokens — single source of truth for UI colors. Anthropic-inspired
// dark palette, AMOLED-friendly (true black bg).
//
// The six non-semantic tokens read through g_theme (device_config.{h,cpp}),
// so a device_config_set_theme() + restart re-skins every call site with no
// further changes needed — see ui.cpp's COL_* indirection. Background is
// pinned to 0x000000 in every preset (not themeable): splash.cpp's shared
// Splash/Copilot/Aurora canvas fills empty pixels with a hardcoded black
// literal outside this system (CLAUDE.md gotcha #13 flags that code as
// fragile), and the semantic colors below are explicitly tuned for a black
// background — varying bg would require touching both.
#define THEME_BG       lv_color_hex(g_theme.bg)      // screen background
#define THEME_PANEL    lv_color_hex(g_theme.panel)   // card/zone fill
#define THEME_TEXT     lv_color_hex(g_theme.text)    // primary text
#define THEME_DIM      lv_color_hex(g_theme.dim)     // secondary text
#define THEME_ACCENT   lv_color_hex(g_theme.accent)  // brand — chrome/brand only
#define THEME_GREEN    lv_color_hex(0x8faa6a)   // "healthy" state (lightened for contrast on black)
#define THEME_AMBER    lv_color_hex(0xe0a458)   // "caution" state — distinct from ACCENT
#define THEME_RED      lv_color_hex(0xc0392b)   // "critical" state
#define THEME_BAR_BG   lv_color_hex(g_theme.bar_bg)  // unfilled bar track
