#include <Arduino.h>
#include <lvgl.h>
#include <ArduinoJson.h>
#include "display_cfg.h"
#include "data.h"
#include "ui.h"
#include "ble.h"
#include "power.h"
#include "imu.h"
#include "splash.h"
#include "usage_rate.h"

// Physical buttons:
//   BTN_BACK  (GPIO 0 / BOOT) — cycle screens (splash→usage→bluetooth→usage…)
//   NOTE: GPIO18 is LCD SCLK on this board — right button not available
//   NOTE: AXP2101 PWR button not available on this board
#define BTN_BACK 0

// ---- Hardware objects ----
// ST7789 via hardware SPI (VSPI: MOSI=23, SCLK=18)
// col_offset=52, row_offset=40 are standard for 1.14" 135x240 ST7789 panels
Arduino_DataBus *bus = new Arduino_ESP32SPI(
    LCD_DC, LCD_CS, LCD_SCLK, LCD_MOSI, GFX_NOT_DEFINED /* MISO */);
Arduino_ST7789  *gfx = new Arduino_ST7789(
    bus, LCD_RESET, 0 /* rotation */, true /* IPS */,
    LCD_WIDTH, LCD_HEIGHT, 52, 40);

static UsageData usage = {};
static CopilotData copilot = {};

// ---- LVGL draw buffers (partial render) ----
#define BUF_LINES 40
static uint16_t *buf1 = nullptr;
static uint16_t *buf2 = nullptr;

// LVGL tick callback
static uint32_t my_tick(void) {
    return millis();
}

// LVGL flush callback — ST7789 direct SPI write, no rotation needed
static void my_flush_cb(lv_display_t* disp, const lv_area_t* area, uint8_t* px_map) {
    int32_t w = area->x2 - area->x1 + 1;
    int32_t h = area->y2 - area->y1 + 1;
    gfx->draw16bitRGBBitmap(area->x1, area->y1, (uint16_t*)px_map, w, h);
    lv_display_flush_ready(disp);
}

// Parse a JSON line into UsageData or CopilotData based on the "src" field.
// Dispatching is done at the call site in loop().

// Serial command buffer
#define CMD_BUF_SIZE 64
static char cmd_buf[CMD_BUF_SIZE];
static int cmd_pos = 0;

static void send_screenshot() {
    const uint32_t w = LCD_WIDTH, h = LCD_HEIGHT;
    const uint32_t row_bytes = w * 2;
    const uint32_t buf_size = row_bytes * h;
    uint8_t* sbuf = (uint8_t*)malloc(buf_size);
    if (!sbuf) {
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    lv_draw_buf_t draw_buf;
    lv_draw_buf_init(&draw_buf, w, h, LV_COLOR_FORMAT_RGB565, row_bytes, sbuf, buf_size);

    lv_result_t res = lv_snapshot_take_to_draw_buf(lv_screen_active(), LV_COLOR_FORMAT_RGB565, &draw_buf);
    if (res != LV_RESULT_OK) {
        free(sbuf);
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    Serial.printf("SCREENSHOT_START %lu %lu %lu\n", (unsigned long)w, (unsigned long)h, (unsigned long)buf_size);
    Serial.flush();
    Serial.write(sbuf, buf_size);
    Serial.flush();
    Serial.println();
    Serial.println("SCREENSHOT_END");

    free(sbuf);
}

static void check_serial_cmd() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            cmd_buf[cmd_pos] = '\0';
            if (strcmp(cmd_buf, "screenshot") == 0) {
                send_screenshot();
            }
            cmd_pos = 0;
        } else if (cmd_pos < CMD_BUF_SIZE - 1) {
            cmd_buf[cmd_pos++] = c;
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("{\"ready\":true}");

    // Init display
    gfx->begin();
    gfx->fillScreen(0x0000);
    // Enable LCD backlight
    pinMode(LCD_BLK, OUTPUT);
    digitalWrite(LCD_BLK, HIGH);

    // Init PMU stub (no-op)
    power_init();

    // Init IMU stub (no-op)
    imu_init();

    // Init LVGL
    lv_init();
    lv_tick_set_cb(my_tick);

    // Allocate partial render buffers (no PSRAM on ESP32-WROOM)
    buf1 = (uint16_t*)malloc(LCD_WIDTH * BUF_LINES * 2);
    buf2 = (uint16_t*)malloc(LCD_WIDTH * BUF_LINES * 2);

    lv_display_t* disp = lv_display_create(LCD_WIDTH, LCD_HEIGHT);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(disp, my_flush_cb);
    lv_display_set_buffers(disp, buf1, buf2, LCD_WIDTH * BUF_LINES * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    // Init BLE data channel
    ble_init();

    // Physical button: back (GPIO 0 / BOOT button)
    pinMode(BTN_BACK, INPUT_PULLUP);

    // Build dashboard
    ui_init();

    // Show initial BLE status on Bluetooth screen
    ui_update_ble_status(ble_get_state(), ble_get_device_name(), ble_get_mac_address());

    // Show initial battery status
    ui_update_battery(power_battery_pct(), power_is_charging());

    ui_show_screen(SCREEN_SPLASH);

    Serial.println("Dashboard ready, waiting for data on BLE...");
}

static ble_state_t last_ble_state = BLE_STATE_INIT;

void loop() {
    lv_timer_handler();
    ui_tick_anim();
    ble_tick();
    power_tick();
    imu_tick();
    splash_tick();

    // Single button (GPIO 0 / BOOT):
    //   Press on splash       → advance to Usage screen
    //   Press on Usage/BT     → cycle Usage ↔ Bluetooth
    //   NOTE: GPIO18 = LCD SCLK (no right button); AXP PWR not present
    {
        static bool back_was = false;
        bool back_now = (digitalRead(BTN_BACK) == LOW);

        if (back_now && !back_was) {
            if (ui_get_current_screen() == SCREEN_SPLASH) ui_show_screen(SCREEN_USAGE);
            else                                          ui_cycle_screen();
        }
        back_was = back_now;
    }

    // Update BLE status on screen when state changes
    ble_state_t bs = ble_get_state();
    if (bs != last_ble_state) {
        last_ble_state = bs;
        ui_update_ble_status(bs, ble_get_device_name(), ble_get_mac_address());
    }

    // Update battery indicator
    static int last_pct = -2;
    static bool last_charging = false;
    int pct = power_battery_pct();
    bool charging = power_is_charging();
    if (pct != last_pct || charging != last_charging) {
        last_pct = pct;
        last_charging = charging;
        ui_update_battery(pct, charging);
    }

    // Check for serial commands (screenshot, etc.)
    check_serial_cmd();

    // Process incoming BLE data — route by "src" field (default: "claude")
    if (ble_has_data()) {
        const char* raw = ble_get_data();
        JsonDocument doc;
        if (deserializeJson(doc, raw) != DeserializationError::Ok) {
            Serial.println("JSON parse error");
            ble_send_nack();
        } else {
            const char* src = doc["src"] | "claude";
            if (strcmp(src, "copilot") == 0) {
                copilot.premium_pct       = doc["pp"]  | -1;
                copilot.premium_remaining = doc["pr"]  | -1;
                copilot.premium_total     = doc["pe"]  | -1;
                copilot.premium_reset_mins = doc["prm"] | -1;
                strlcpy(copilot.premium_reset_str, doc["prd"] | "---", sizeof(copilot.premium_reset_str));
                strlcpy(copilot.plan, doc["plan"] | "unknown", sizeof(copilot.plan));
                copilot.enabled = doc["en"]  | false;
                copilot.valid   = true;
                ui_update_copilot(&copilot);
                ble_send_ack();
            } else {
                usage.session_pct        = doc["s"]  | 0.0f;
                usage.session_reset_mins = doc["sr"] | -1;
                usage.weekly_pct         = doc["w"]  | 0.0f;
                usage.weekly_reset_mins  = doc["wr"] | -1;
                strlcpy(usage.status, doc["st"] | "unknown", sizeof(usage.status));
                usage.ok    = doc["ok"] | false;
                usage.valid = true;
                int g_before = usage_rate_group();
                usage_rate_sample(usage.session_pct);
                int g_after = usage_rate_group();
                if (g_after != g_before) {
                    Serial.printf("usage rate: group %d -> %d (s=%.2f%%)\n",
                        g_before, g_after, usage.session_pct);
                    if (splash_is_active()) splash_pick_for_current_rate();
                }
                ui_update(&usage);
                ble_send_ack();
            }
        }
    }

    delay(5);
}
