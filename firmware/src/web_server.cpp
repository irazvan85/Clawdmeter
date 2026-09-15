#include "web_server.h"
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>
#include "device_api.h"
#include "display_cfg.h"
#include "web_ui.h"
#include "wifi_net.h"

static WebServer server(80);

static void handle_root() {
    server.sendHeader("Content-Encoding", "gzip");
    server.send_P(200, "text/html", (PGM_P)INDEX_HTML_GZ, INDEX_HTML_GZ_LEN);
}

static void handle_state() {
    JsonDocument doc;
    build_state_json(doc);
    String out;
    serializeJson(doc, out);
    server.send(200, "application/json", out);
}

// Replaces BLE's RX characteristic write as the daemon's data-push path
// (see CLAUDE.md gotcha #14 for why BLE was removed). The only mutating
// route, so it's the only one that checks the auth token -- GET /api/state
// deliberately never exposes wifi_get_token(), or an unauthenticated read
// route would leak the credential that's supposed to gate this one.
static void handle_payload() {
    if (server.header("X-Auth-Token") != wifi_get_token()) {
        server.send(401, "text/plain", "bad token");
        return;
    }
    String body = server.arg("plain");
    if (device_ingest_payload(body.c_str())) {
        server.send(200, "application/json", "{\"ok\":true}");
    } else {
        server.send(400, "application/json", "{\"ok\":false}");
    }
}

static void write_le16(uint8_t* p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void write_le32(uint8_t* p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

// Converts one flushed tile (RGB565, up to BUF_LINES rows tall, always full
// display width -- see main.cpp's BUF_LINES/my_flush_cb) to BGR888 and
// streams it straight into the in-flight HTTP response. Tiles arrive
// strictly top-to-bottom (capture_screenshot() forces one full-screen
// invalidate, then a partial-buffer redraw always flushes that way) -- the
// BMP header below declares a *negative* height specifically so rows can be
// written in that same top-down order without buffering/reversing anything.
static void screenshot_tile_to_http(int x1, int y1, int x2, int y2, const uint16_t* pixels) {
    (void)y1; (void)y2;
    const int w = x2 - x1 + 1;
    const int row_bytes = ((LCD_WIDTH * 3 + 3) / 4) * 4;  // BMP rows padded to a 4-byte boundary
    int h = y2 - y1 + 1;
    uint8_t row[LCD_WIDTH * 3 + 3] = {0};
    for (int ty = 0; ty < h; ty++) {
        const uint16_t* src = &pixels[ty * w];
        for (int tx = 0; tx < w; tx++) {
            uint16_t px = src[tx];
            uint8_t r = (px >> 11) & 0x1F, g = (px >> 5) & 0x3F, b = px & 0x1F;
            int dst = (x1 + tx) * 3;
            row[dst + 0] = (uint8_t)((b * 255) / 31);  // BMP pixel order is BGR
            row[dst + 1] = (uint8_t)((g * 255) / 63);
            row[dst + 2] = (uint8_t)((r * 255) / 31);
        }
        server.sendContent((const char*)row, row_bytes);
    }
}

// Captures the current frame and streams it as an uncompressed 24-bpp BMP —
// any browser renders that with a plain <img>, no client-side decode needed.
// No frame buffer is ever allocated (see capture_screenshot_streamed()'s
// comment in device_api.h) -- a single ~65 KB malloc() here used to fail
// under real load ("out of memory"), since WiFi + an active daemon
// connection are also holding heap.
static void handle_screenshot() {
    const int w = LCD_WIDTH, h = LCD_HEIGHT;
    const int row_bytes = ((w * 3 + 3) / 4) * 4;  // BMP rows padded to a 4-byte boundary
    const uint32_t pixel_data_size = (uint32_t)row_bytes * (uint32_t)h;
    const uint32_t file_size = 54 + pixel_data_size;

    uint8_t hdr[54] = {0};
    hdr[0] = 'B'; hdr[1] = 'M';
    write_le32(&hdr[2],  file_size);
    write_le32(&hdr[10], 54);            // pixel data offset
    write_le32(&hdr[14], 40);            // DIB header size (BITMAPINFOHEADER)
    write_le32(&hdr[18], (uint32_t)w);
    write_le32(&hdr[22], (uint32_t)-h);  // NEGATIVE height = top-down row order
    write_le16(&hdr[26], 1);             // planes
    write_le16(&hdr[28], 24);            // bpp
    write_le32(&hdr[34], pixel_data_size);

    server.setContentLength(file_size);
    server.send(200, "image/bmp", "");
    server.sendContent((const char*)hdr, sizeof(hdr));

    capture_screenshot_streamed(screenshot_tile_to_http);
}

static bool started = false;

void web_server_init(void) {
    // Routes only -- server.begin() is deferred to web_server_tick() below,
    // once WiFi actually has a real IP. Calling WebServer::begin() (which
    // creates+binds+listens a socket) before that crashes on this
    // esp32-arduino version (lwIP's tcpip thread isn't fully up) or hangs
    // handleClient() indefinitely (interface exists but has no IP yet) --
    // this is also just the standard, widely-used ESP32 Arduino pattern.

    // WebServer only makes a header available via header() if it was asked
    // to collect it up front -- without this, handle_payload()'s token
    // check would silently always see an empty string.
    static const char* kHeaders[] = {"X-Auth-Token"};
    server.collectHeaders(kHeaders, 1);

    server.on("/", HTTP_GET, handle_root);
    server.on("/api/state", HTTP_GET, handle_state);
    server.on("/api/screenshot.bmp", HTTP_GET, handle_screenshot);
    server.on("/api/payload", HTTP_POST, handle_payload);
}

void web_server_tick(void) {
    if (!started) {
        if (wifi_get_state() != WIFI_STATE_CONNECTED) return;
        server.begin();
        // Lets the daemon find the device at clawdmeter.local instead of
        // needing a hardcoded/rediscovered IP (see CLAUDE.md gotcha #14 --
        // this is the daemon's discovery mechanism now that BLE is gone).
        if (MDNS.begin("clawdmeter")) {
            MDNS.addService("http", "tcp", 80);
        }
        started = true;
    }
    server.handleClient();
}
