#pragma once
#include <lvgl.h>

// Design tokens — single source of truth for UI colors. Anthropic-inspired
// dark palette, AMOLED-friendly (true black bg).
#define THEME_BG       lv_color_hex(0x000000)   // screen background
#define THEME_PANEL    lv_color_hex(0x1f1f1e)   // card/zone fill
#define THEME_TEXT     lv_color_hex(0xfaf9f5)   // primary text
#define THEME_DIM      lv_color_hex(0xb0aea5)   // secondary text
#define THEME_ACCENT   lv_color_hex(0xd97757)   // brand terra-cotta — chrome/brand only
#define THEME_GREEN    lv_color_hex(0x8faa6a)   // "healthy" state (lightened for contrast on black)
#define THEME_AMBER    lv_color_hex(0xe0a458)   // "caution" state — distinct from ACCENT
#define THEME_RED      lv_color_hex(0xc0392b)   // "critical" state
#define THEME_BAR_BG   lv_color_hex(0x2a2a28)   // unfilled bar track
