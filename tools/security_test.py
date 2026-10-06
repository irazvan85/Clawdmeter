#!/usr/bin/env python3
"""Black-box HTTP security regression suite for the device's web server
(firmware/src/web_server.cpp). There's no ESP32 emulator in this repo, so
this exercises a real, already-flashed, already-WiFi-connected device --
run it after `run`-skill flashing, against the IP/token shown on the
device's Connectivity screen.

Usage:
    python tools/security_test.py --host clawdmeter.local --token ABCD2345
    python tools/security_test.py --host 192.168.1.42 --serial-port COM13

--serial-port reads the token itself via the `token` serial command instead
of requiring it on the command line (handy for CI on the bench, where the
device is both flashed and reachable over WiFi at the same time).

Some checks mutate device state (screen-visibility mask, the "status"/"ci"
payload fields) -- each one restores what it changed. None of them trigger
an actual reboot by default; --allow-restart opts into the one check that
does (an in-range theme change), which takes ~15s to recover from.

Exit code 0 if every check passed, 1 otherwise.
"""
import argparse
import re
import sys
import time

try:
    import httpx
except ImportError:
    sys.exit("httpx not found -- `pip install httpx` (see daemon/requirements.txt)")

TOKEN_CHARSET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
CLOCK_BIT = 1 << 0
CONN_BIT = 1 << 8


def get_token_via_serial(port_path: str) -> str:
    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial not found -- `pip install pyserial`, or pass --token directly")
    port = serial.Serial(port_path, 115200, timeout=2)
    try:
        time.sleep(2.5)  # opening the port resets the ESP32 on many adapters
        port.reset_input_buffer()
        port.write(b"token\n")
        port.flush()
        deadline = time.time() + 5
        while time.time() < deadline:
            line = port.readline().decode("utf-8", "replace").strip()
            if len(line) == 8 and set(line) <= TOKEN_CHARSET:
                return line
        sys.exit("no token line read over serial within 5s")
    finally:
        port.close()


class Suite:
    def __init__(self, base_url: str, token: str, allow_restart: bool) -> None:
        self.client = httpx.Client(base_url=base_url, timeout=10.0)
        self.token = token
        self.allow_restart = allow_restart
        self.passed = 0
        self.failed = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"PASS  {name}")
        else:
            self.failed += 1
            print(f"FAIL  {name}" + (f"  -- {detail}" if detail else ""))

    def auth_header(self, token: str | None = None) -> dict:
        return {"X-Auth-Token": token if token is not None else self.token}

    # ---- individual checks ----

    def payload_requires_token(self) -> None:
        r = self.client.post("/api/payload", content=b'{"src":"status","state":"ok"}')
        self.check("payload_requires_token", r.status_code == 401, f"got {r.status_code}")

    def payload_rejects_wrong_token(self) -> None:
        r = self.client.post(
            "/api/payload",
            headers=self.auth_header("WRONGTOK"),
            content=b'{"src":"status","state":"ok"}',
        )
        self.check("payload_rejects_wrong_token", r.status_code == 401, f"got {r.status_code}")

    def payload_accepts_valid_token(self) -> None:
        r = self.client.post(
            "/api/payload",
            headers={**self.auth_header(), "Content-Type": "application/json"},
            content=b'{"src":"status","state":"ok"}',
        )
        ok = r.status_code == 200 and r.json().get("ok") is True
        self.check("payload_accepts_valid_token", ok, f"got {r.status_code} {r.text!r}")

    def state_never_leaks_token(self) -> None:
        r = self.client.get("/api/state")
        self.check(
            "state_never_leaks_token",
            r.status_code == 200 and self.token not in r.text,
            "token substring found in /api/state" if self.token in r.text else f"got {r.status_code}",
        )

    def config_post_requires_token(self) -> None:
        r = self.client.post("/api/config", data={"mask": "1"})
        self.check("config_post_requires_token", r.status_code == 401, f"got {r.status_code}")

    def config_post_rejects_wrong_token(self) -> None:
        r = self.client.post("/api/config", headers=self.auth_header("WRONGTOK"), data={"mask": "1"})
        self.check("config_post_rejects_wrong_token", r.status_code == 401, f"got {r.status_code}")

    def screenshot_requires_token(self) -> None:
        # Regression guard: GET /api/screenshot.bmp used to ship unauthenticated
        # even though the Connectivity screen renders the token as on-screen
        # text -- an unauthenticated screenshot could read it straight off the
        # frame. See CLAUDE.md for the writeup.
        r = self.client.get("/api/screenshot.bmp")
        self.check("screenshot_requires_token", r.status_code == 401, f"got {r.status_code}")

    def screenshot_accepts_valid_token(self) -> None:
        r = self.client.get("/api/screenshot.bmp", headers=self.auth_header())
        ok = (
            r.status_code == 200
            and r.headers.get("content-type") == "image/bmp"
            and r.content[:2] == b"BM"
            and len(r.content) > 54
        )
        self.check("screenshot_accepts_valid_token", ok, f"got {r.status_code}, {len(r.content)} bytes")

    def mask_zero_forces_required_bits(self) -> None:
        orig = self.client.get("/api/config").json()
        try:
            r = self.client.post("/api/config", headers=self.auth_header(), data={"mask": "0"})
            after = self.client.get("/api/config").json()
            mask = after.get("visible_mask", 0)
            ok = r.status_code == 200 and (mask & CLOCK_BIT) and (mask & CONN_BIT)
            self.check(
                "mask_zero_forces_required_bits", bool(ok),
                f"visible_mask=0x{mask:03x} after posting mask=0 (Clock/Connectivity bits must survive)",
            )
        finally:
            self.client.post("/api/config", headers=self.auth_header(), data={"mask": str(orig["visible_mask"])})

    def theme_out_of_range_rejected_without_restart(self) -> None:
        orig = self.client.get("/api/config").json()
        r = self.client.post("/api/config", headers=self.auth_header(), data={"theme": "99"})
        body = r.json() if r.status_code == 200 else {}
        after = self.client.get("/api/config").json()
        ok = (
            r.status_code == 200
            and body.get("restart") is False
            and after.get("theme") == orig.get("theme")
        )
        self.check(
            "theme_out_of_range_rejected_without_restart", ok,
            f"response={body}, theme before={orig.get('theme')} after={after.get('theme')}",
        )
        # A restart here would mean an invalid value still tore down the
        # device -- confirm it's still promptly reachable either way.
        r2 = self.client.get("/api/state")
        self.check("device_reachable_after_invalid_theme_post", r2.status_code == 200, f"got {r2.status_code}")

    def theme_change_actually_restarts(self) -> None:
        if not self.allow_restart:
            print("SKIP  theme_change_actually_restarts (pass --allow-restart to run; takes ~15s)")
            return
        orig = self.client.get("/api/config").json()
        other = 1 if orig["theme"] != 1 else 0
        try:
            r = self.client.post("/api/config", headers=self.auth_header(), data={"theme": str(other)})
            body = r.json() if r.status_code == 200 else {}
            self.check("theme_change_reports_restart_true", body.get("restart") is True, f"got {body}")
            time.sleep(18)
            r2 = self.client.get("/api/state")
            self.check("device_back_up_after_restart", r2.status_code == 200, f"got {r2.status_code}")
        finally:
            self.client.post("/api/config", headers=self.auth_header(), data={"theme": str(orig["theme"])})
            time.sleep(18)

    def malformed_json_rejected_without_crash(self) -> None:
        bad_bodies = [
            b"{not json",
            b"",
            b'{"src":"copilot","plan":"' + b"A" * 500 + b'"}',
            b'{"src":"ci","branch":"' + b'"; DROP TABLE x;--' + b'"}',
        ]
        all_ok = True
        for body in bad_bodies:
            r = self.client.post(
                "/api/payload",
                headers={**self.auth_header(), "Content-Type": "application/json"},
                content=body,
            )
            if r.status_code not in (200, 400):
                all_ok = False
        alive = self.client.get("/api/state")
        ok = all_ok and alive.status_code == 200
        self.check("malformed_json_rejected_without_crash", ok, "device did not stay reachable/consistent")

    def oversized_unauthenticated_body_does_not_wedge_device(self) -> None:
        big = b"x" * (256 * 1024)
        try:
            r = self.client.post("/api/payload", content=big, timeout=10.0)
            status_ok = r.status_code == 401
        except httpx.HTTPError:
            status_ok = True  # a dropped/reset connection is an acceptable outcome too
        alive = self.client.get("/api/state", timeout=5.0)
        self.check(
            "oversized_unauthenticated_body_does_not_wedge_device",
            status_ok and alive.status_code == 200,
            f"status_ok={status_ok}, alive={alive.status_code if alive else 'unreachable'}",
        )

    def form_content_type_body_rejected(self) -> None:
        # Documented gotcha: WebServer only populates server.arg("plain") for
        # application/json bodies -- a form-encoded POST (curl -d's default)
        # gets an empty body and a 400, nothing to do with the token check.
        r = self.client.post(
            "/api/payload",
            headers={**self.auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
            content=b'{"src":"status","state":"ok"}',
        )
        self.check("form_content_type_body_rejected", r.status_code == 400, f"got {r.status_code}")

    def run_all(self) -> int:
        for name in (
            "payload_requires_token",
            "payload_rejects_wrong_token",
            "payload_accepts_valid_token",
            "state_never_leaks_token",
            "config_post_requires_token",
            "config_post_rejects_wrong_token",
            "screenshot_requires_token",
            "screenshot_accepts_valid_token",
            "mask_zero_forces_required_bits",
            "theme_out_of_range_rejected_without_restart",
            "theme_change_actually_restarts",
            "malformed_json_rejected_without_crash",
            "oversized_unauthenticated_body_does_not_wedge_device",
            "form_content_type_body_rejected",
        ):
            try:
                getattr(self, name)()
            except httpx.HTTPError as e:
                self.failed += 1
                print(f"FAIL  {name}  -- request error: {e}")
        print(f"\n{self.passed} passed, {self.failed} failed")
        return 1 if self.failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="device hostname or IP, e.g. clawdmeter.local")
    ap.add_argument("--token", help="device auth token (or use --serial-port to read it live)")
    ap.add_argument("--serial-port", help="serial port to read the token from, e.g. COM13")
    ap.add_argument("--allow-restart", action="store_true", help="also run the in-range theme-change/restart check")
    args = ap.parse_args()

    token = args.token
    if not token and args.serial_port:
        token = get_token_via_serial(args.serial_port)
    if not token:
        sys.exit("need --token or --serial-port")

    suite = Suite(f"http://{args.host}", token, args.allow_restart)
    sys.exit(suite.run_all())


if __name__ == "__main__":
    main()
