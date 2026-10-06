#pragma once

// HTTP surface over WiFi (see wifi_net.h) — the sole transport now that
// BLE has been removed (CLAUDE.md gotcha #14). The dashboard page, a JSON
// mirror of device state, an on-demand screenshot, and the current
// theme/visibility config are open reads; POST /api/payload (the daemon's
// data-push path, replacing BLE's RX characteristic) and POST /api/config
// (theme + screen-visibility settings, Phase 2) are the mutating routes and
// both require the X-Auth-Token header to match wifi_get_token().

void web_server_init(void);   // call once from setup(); safe before WiFi connects
void web_server_tick(void);   // call every loop(); drives WebServer::handleClient()
