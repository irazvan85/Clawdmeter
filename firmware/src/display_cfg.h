#pragma once

// Target: ideaspark ESP32 1.14" ST7789 135x240 SPI LCD
// Pin reference: doc/spec.md, doc/pinlayout.md
#include <Arduino_GFX_Library.h>

// ---- Display resolution ----
#define LCD_WIDTH   135
#define LCD_HEIGHT  240

// ---- SPI display pins (ST7789) ----
#define LCD_MOSI    23
#define LCD_SCLK    18
#define LCD_CS      15
#define LCD_DC       2
#define LCD_RESET    4
#define LCD_BLK     32

// ---- Global hardware objects (defined in main.cpp) ----
extern Arduino_DataBus *bus;
extern Arduino_ST7789  *gfx;
