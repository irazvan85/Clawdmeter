#!/usr/bin/env python3
"""Runtime performance + heap check against a real, flashed device.

The runtime counterpart to tools/resource_report.py (static/link-time
budgets). Reads the firmware's perf counters (firmware/src/perf.{h,cpp}) --
loop time, lv_timer_handler() time, free heap, heap low-water mark, largest
free block -- and gates on them. This is the check that would have caught
CLAUDE.md gotcha #14 (static RAM fine, runtime heap exhausted).

Two transports, use either or both:

  --serial COM13   Opening the port resets the ESP32 (DTR/RTS), so this
                   measures a cold boot: waits for "Dashboard ready", feeds
                   every fixture payload (tools/fixtures/payloads.json) so
                   all 7 lazily-built screens actually get built, then visits
                   every screen via `screen <n>` and records the worst
                   lv_timer_handler() time per screen (first show = widget
                   build + full redraw, the path that hung in gotcha #13).
                   Ends with a settle window measuring steady-state loop time.

  --host IP        No reset. Times GET /api/state (and, with --token, GET
                   /api/screenshot.bmp -- the route that used to OOM, gotcha
                   #15), and reads the same counters from /api/state's
                   "device" object while WiFi + HTTP are live, which is the
                   heap state the serial run can't see.

Thresholds (fail / warn) are in LIMITS below. Writes a Markdown report to
--report (default: firmware/.pio/build/<env>/perf_report.md).

Needs pyserial for --serial (PlatformIO's penv python has it) and httpx for
--host (daemon/requirements.txt). Exit 1 if any FAIL.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "payloads.json"
DEFAULT_REPORT = ROOT / "firmware" / ".pio" / "build" / "ideaspark_114_st7789" / "perf_report.md"

SCREEN_NAMES = ["Splash", "Clock", "Sensor", "Sensor Trend", "Usage", "Copilot",
                "SysInfo", "VS Code", "Connectivity", "Checks", "Today", "Aurora", "Codex",
                "Air", "Gases"]

WIFI_STATES = {0: "off (no credentials)", 1: "connecting", 2: "connected", 3: "failed"}

# metric: (fail_if, warn_if, "lt"/"gt"). Heap numbers in bytes, times in us/ms.
LIMITS = {
    # Largest free block -- WiFi.begin() refuses below 50 KB
    # (WIFI_MIN_MAX_ALLOC_BEGIN, wifi_net.cpp); 65 KB is the ~65 KB the old
    # screenshot path needed in one piece.
    "max_alloc_min":  (30_000, 50_000, "lt"),
    "heap_min_free":  (25_000, 45_000, "lt"),
    "lv_max_us":      (1_000_000, 300_000, "gt"),   # one LVGL pass: 1 s = hang-adjacent
    "loop_avg_us":    (50_000, 15_000, "gt"),
    "state_p95_ms":   (2_000, 500, "gt"),
    "shot_ms":        (15_000, 5_000, "gt"),
}


class Results:
    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []   # (section, metric, value, verdict)
        self.fails = 0
        self.warns = 0

    def gate(self, section: str, metric: str, value, key: str | None = None, unit: str = ""):
        verdict = "info"
        if key and value is not None:
            fail, warn, op = LIMITS[key]
            bad = (lambda lim: value < lim) if op == "lt" else (lambda lim: value > lim)
            verdict = "FAIL" if bad(fail) else "warn" if bad(warn) else "ok"
        self.fails += verdict == "FAIL"
        self.warns += verdict == "warn"
        shown = f"{value:,}{unit}" if isinstance(value, int) else f"{value}{unit}"
        self.rows.append((section, metric, shown, verdict))

    def markdown(self) -> str:
        out = ["# Device performance report", "",
               f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
               "| Section | Metric | Value | Verdict |", "|---|---|---:|---|"]
        out += [f"| {s} | {m} | {v} | {d} |" for s, m, v, d in self.rows]
        out += ["", f"**{self.fails} fail, {self.warns} warn**", "",
                "Thresholds: see LIMITS in tools/perf_check.py."]
        return "\n".join(out) + "\n"


# ------------------------------------------------------------------ serial

class Dev:
    """Line-oriented serial session that never sleeps without draining the
    port (CLAUDE.md gotcha #14's testing note)."""

    def __init__(self, port: str):
        import serial  # pyserial
        self.s = serial.Serial(port, 115200, timeout=0.1)
        self.log: list[str] = []

    def wait_for(self, pred, timeout: float) -> str | None:
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            buf += self.s.read(4096)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self.log.append(text)
                    if pred(text):
                        return text
        return None

    def cmd(self, c: str, pred=None, timeout: float = 3.0) -> str | None:
        self.s.write((c + "\n").encode())
        return self.wait_for(pred or (lambda _l: True), timeout)

    def perf(self) -> dict | None:
        line = self.cmd("perf", lambda l: l.startswith('{"perf"'))
        return json.loads(line)["perf"] if line else None


def run_serial(port: str, r: Results, settle_s: float) -> None:
    d = Dev(port)
    t0 = time.time()
    if not d.wait_for(lambda l: l.startswith("Dashboard ready"), 20):
        r.gate("boot", "reached setup() end", "no 'Dashboard ready' in 20 s")
        r.fails += 1
        return
    r.gate("boot", "boot to 'Dashboard ready'", f"{time.time() - t0:.1f}", unit=" s")
    p = d.perf()
    if not p:
        r.gate("boot", "perf command", "no reply -- firmware without perf.cpp?")
        r.fails += 1
        return
    r.gate("boot", "heap free after setup()", p["heap_free"])
    r.gate("boot", "largest free block after setup()", p["max_alloc"], "max_alloc_min")

    fixtures = {k: v for k, v in json.loads(FIXTURES.read_text()).items() if not k.startswith("_")}
    for name, payload in fixtures.items():
        ok = d.cmd("feed " + json.dumps(payload, separators=(",", ":")),
                   lambda l: l in ("feed ok", "feed err", "JSON parse error"))
        if ok != "feed ok":
            r.gate("feed", f"feed {name}", f"got {ok!r}")
            r.fails += 1

    worst = 0
    for n, label in enumerate(SCREEN_NAMES):
        d.cmd("perf reset", lambda l: l == "perf reset")
        d.cmd(f"screen {n}", lambda l: l.startswith("screen ->"))
        d.wait_for(lambda _l: False, 0.8)     # let a few loop()s render, draining the port
        p = d.perf()
        if not p:
            r.gate("screens", label, "no perf reply (hung?)")
            r.fails += 1
            continue
        worst = max(worst, p["lv_max_us"])
        r.gate("screens", f"{n} {label}: worst LVGL pass", p["lv_max_us"], "lv_max_us", " us")
    r.gate("screens", "worst LVGL pass, all screens", worst, "lv_max_us", " us")

    d.cmd("screen 1", lambda l: l.startswith("screen ->"))
    d.cmd("perf reset", lambda l: l == "perf reset")
    d.wait_for(lambda _l: False, settle_s)
    p = d.perf() or {}
    r.gate("steady", f"loop avg over {settle_s:.0f} s", p.get("loop_avg_us"), "loop_avg_us", " us")
    r.gate("steady", "loop max", p.get("loop_max_us"), unit=" us")
    r.gate("steady", "heap free", p.get("heap_free"))
    r.gate("steady", "heap low-water since boot", p.get("heap_min_free"), "heap_min_free")
    r.gate("steady", "smallest largest-free-block seen", p.get("max_alloc_min"), "max_alloc_min")
    ws = p.get("wifi_state")
    r.gate("steady", "WiFi state", f"{WIFI_STATES.get(ws, ws)} {p.get('wifi_ip') or ''}".strip())
    crashes = [l for l in d.log if "Guru Meditation" in l or "assert failed" in l or "Backtrace" in l]
    if crashes:
        r.gate("stability", "crash output on serial", crashes[0][:80])
        r.fails += 1
    else:
        r.gate("stability", "crash output on serial", "none")


# -------------------------------------------------------------------- http

def run_http(host: str, token: str | None, r: Results, n: int) -> None:
    import httpx
    base = f"http://{host}"
    lat = []
    device = None
    with httpx.Client(timeout=10) as c:
        for _ in range(n):
            t = time.perf_counter()
            resp = c.get(f"{base}/api/state")
            lat.append((time.perf_counter() - t) * 1000)
            resp.raise_for_status()
            device = resp.json().get("device")
        lat.sort()
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        r.gate("http", f"GET /api/state median ({n}x)", f"{statistics.median(lat):.0f}", unit=" ms")
        r.gate("http", "GET /api/state p95", round(p95), "state_p95_ms", " ms")
        if token:
            t = time.perf_counter()
            resp = c.get(f"{base}/api/screenshot.bmp", headers={"X-Auth-Token": token})
            ms = round((time.perf_counter() - t) * 1000)
            if resp.status_code != 200:
                r.gate("http", "GET /api/screenshot.bmp", f"HTTP {resp.status_code}")
                r.fails += 1
            else:
                r.gate("http", f"GET /api/screenshot.bmp ({len(resp.content):,} B)", ms, "shot_ms", " ms")
            device = c.get(f"{base}/api/state").json().get("device", device)
    if not device:
        r.gate("http", "device counters", "missing from /api/state -- firmware without perf.cpp?")
        r.fails += 1
        return
    r.gate("live", "uptime", device["uptime_s"], unit=" s")
    r.gate("live", "reset reason (esp_reset_reason_t)", device["reset_reason"])
    r.gate("live", "heap free (WiFi+HTTP live)", device["heap_free"])
    r.gate("live", "heap low-water since boot", device["heap_min_free"], "heap_min_free")
    r.gate("live", "smallest largest-free-block (window)", device["max_alloc_min"], "max_alloc_min")
    r.gate("live", "loop avg", device["loop_avg_us"], "loop_avg_us", " us")
    r.gate("live", "worst LVGL pass (window)", device["lv_max_us"], "lv_max_us", " us")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="Runtime perf/heap check against a real device")
    ap.add_argument("--serial", metavar="PORT", help="e.g. COM13 (resets the device)")
    ap.add_argument("--host", help="device IP or clawdmeter.local")
    ap.add_argument("--token", help="X-Auth-Token, enables the screenshot timing")
    ap.add_argument("--requests", type=int, default=20, help="GET /api/state samples")
    ap.add_argument("--settle", type=float, default=10.0, help="steady-state window (s), serial mode")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    a = ap.parse_args()
    if not a.serial and not a.host:
        ap.error("give --serial PORT and/or --host HOST")

    r = Results()
    if a.serial:
        run_serial(a.serial, r, a.settle)
    if a.host:
        run_http(a.host, a.token, r, a.requests)

    md = r.markdown()
    print(md)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(md, encoding="utf-8")
    print(f"(report: {a.report})")
    return 1 if r.fails else 0


if __name__ == "__main__":
    sys.exit(main())
