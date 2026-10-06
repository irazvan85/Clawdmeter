#!/usr/bin/env python3
"""Standalone CLI for Clawdmeter's UDP broadcast discovery protocol.

Useful for a first-time setup (before device_token/device_host is known) or
for manually confirming the device is reachable without digging through the
daemon's log. Same wire protocol as daemon/claude_usage_daemon.py's
resolve_device_ip() fallback and firmware/src/discovery.{h,cpp} -- see
firmware/src/discovery.h for the protocol rationale (mDNS unreliability on
networks with no Bonjour/avahi, why the reply's source IP is trusted
instead of anything in the payload, why it's unauthenticated by design).

Usage:
    python tools/discover_device.py [--timeout SECONDS] [--port PORT]
"""

import argparse
import socket
import sys
import time

DISCOVERY_PORT = 42424
DISCOVERY_REQUEST = b"CLAWDMETER_DISCOVER_V1"
DISCOVERY_REPLY = b"CLAWDMETER_HELLO_V1"
DISCOVERY_TIMEOUT = 2.0


def discover(timeout: float = DISCOVERY_TIMEOUT, port: int = DISCOVERY_PORT) -> list[str]:
    """Broadcasts one discovery request and collects every valid reply
    received before the timeout, deduplicated. Normally there's only one
    Clawdmeter device on a home LAN, but collecting all replies (rather
    than returning on the first) makes multi-device setups work too and
    makes it obvious if something unexpected is answering."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    found: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        sock.sendto(DISCOVERY_REQUEST, ("255.255.255.255", port))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                break
            if data.startswith(DISCOVERY_REPLY) and addr[0] not in found:
                found.append(addr[0])
    finally:
        sock.close()
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout", type=float, default=DISCOVERY_TIMEOUT,
        help=f"seconds to wait for replies (default: {DISCOVERY_TIMEOUT})",
    )
    parser.add_argument(
        "--port", type=int, default=DISCOVERY_PORT,
        help=f"UDP discovery port (default: {DISCOVERY_PORT})",
    )
    args = parser.parse_args()

    print(f"Broadcasting discovery request on UDP port {args.port}...")
    try:
        devices = discover(timeout=args.timeout, port=args.port)
    except OSError as e:
        print(f"Discovery failed: {e}", file=sys.stderr)
        return 1

    if not devices:
        print("No Clawdmeter device responded.")
        print("Check the device is powered on, connected to this same WiFi")
        print("network/subnet, and that nothing is blocking UDP broadcasts")
        print("(some routers isolate guest networks or block broadcast traffic).")
        return 1

    for ip in devices:
        print(f"Found device at {ip}  (http://{ip}/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
