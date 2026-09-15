#pragma once

// HTTP surface over WiFi (see wifi_net.h) — the sole transport now that
// BLE has been removed (CLAUDE.md gotcha #14). The dashboard page, a JSON
// mirror of device state, and an on-demand screenshot are open reads;
// POST /api/payload (the daemon's data-push path, replacing BLE's RX
// characteristic) is the one mutating route and requires the X-Auth-Token
// header to match wifi_get_token().

void web_server_init(void);   // call once from setup(); safe before WiFi connects
void web_server_tick(void);   // call every loop(); drives WebServer::handleClient()
