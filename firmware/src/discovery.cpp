#include "discovery.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <string.h>
#include "wifi_net.h"

static WiFiUDP udp;
static bool    started = false;

void discovery_init(void) {
    // Nothing to do before WiFi connects -- see discovery_tick(). Mirrors
    // web_server_init()/web_server_tick()'s split (binding a UDP/TCP socket
    // before the interface has an IP is the same class of bug as gotcha #12
    // in CLAUDE.md).
}

void discovery_tick(void) {
    if (!started) {
        if (wifi_get_state() != WIFI_STATE_CONNECTED) return;
        udp.begin(DISCOVERY_UDP_PORT);
        started = true;
    }
    int len = udp.parsePacket();
    if (len <= 0) return;
    char buf[32];
    int n = udp.read(buf, sizeof(buf) - 1);
    if (n <= 0) return;
    buf[n] = '\0';
    if (strncmp(buf, DISCOVERY_REQUEST, strlen(DISCOVERY_REQUEST)) != 0) return;
    udp.beginPacket(udp.remoteIP(), udp.remotePort());
    udp.print(DISCOVERY_REPLY);
    udp.endPacket();
}
