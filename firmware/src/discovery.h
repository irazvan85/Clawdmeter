#pragma once

// Lightweight UDP broadcast discovery -- independent of mDNS. Exists
// because OS-level ".local" resolution (ESPmDNS here, the OS resolver on
// the host) isn't reliable on every network: stock Windows with no Bonjour
// service installed has no mDNS stub resolver at all, so clawdmeter.local
// fails outright (see CLAUDE.md's clawdmeter.local incident write-up).
//
// Protocol: the daemon (or tools/discover_device.py) broadcasts
// DISCOVERY_REQUEST to this UDP port on the local subnet. Any device that
// recognizes the exact string replies with DISCOVERY_REPLY from its own IP.
// The asker reads the IP off the reply packet's source address -- never out
// of the payload -- so there's nothing to spoof via the payload itself.
// Unauthenticated by design, like GET /api/state: the reply reveals only
// "a Clawdmeter device is here", no token or other secret.
//
// Call discovery_init() once from setup() (safe before WiFi connects) and
// discovery_tick() every loop() -- mirrors web_server_tick()'s
// deferred-until-connected pattern.

#define DISCOVERY_UDP_PORT 42424
#define DISCOVERY_REQUEST  "CLAWDMETER_DISCOVER_V1"
#define DISCOVERY_REPLY    "CLAWDMETER_HELLO_V1"

void discovery_init(void);
void discovery_tick(void);
