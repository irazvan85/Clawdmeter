"""Push a filtered, signed copy of the device's state to the cloud dashboard.

Once a minute: GET the device's /api/state over the LAN, keep only the
allowlisted fields, sign, and POST to the Vercel app's /api/ingest (see
cloud/). Outbound-only -- nothing reaches back into the LAN, and the device
never talks to the internet itself (it lacks the heap for TLS anyway).

Config (daemon config file):
  cloud_url      = https://<project>.vercel.app      (unset = disabled)
  cloud_secret   = <same value as the app's INGEST_HMAC_SECRET, >= 32 chars>
  cloud_sections = weather, ci, vscode               (optional extras)

Field allowlist, not a denylist: build_snapshot() names every field it sends.
Never sent: the device auth token (not in /api/state anyway), IPs, SSIDs,
VS Code's last_error text. Opt-in only: weather (reveals your city), ci
(private repo names and PR titles), vscode.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

PUSH_INTERVAL = 60
MAX_BACKOFF = 900
MIN_SECRET_LEN = 32
DEFAULT_SECTIONS = ("air", "indoor", "claude", "activity", "copilot", "codex", "sysinfo", "today", "device")
OPTIONAL_SECTIONS = ("weather", "ci", "vscode")


def _pick(d: dict | None, keys: tuple[str, ...]) -> dict | None:
    if not isinstance(d, dict):
        return None
    if any(k not in d for k in keys):
        return None  # device firmware too old for this section -- skip it whole
    return {k: d[k] for k in keys}


def _air(state: dict) -> dict | None:
    a = state.get("air")
    out = _pick(a, ("present", "warming", "calibrated", "mv", "ratio", "level", "saturated", "hint"))
    if out is None:
        return None
    gases = a.get("gases") or {}
    names = ("co2", "nh3", "alcohol", "toluene", "acetone", "co")
    if any(n not in gases for n in names):
        return None
    out["gases"] = {n: _pick(gases[n], ("ppm", "level")) for n in names}
    return out


def _device(state: dict) -> dict | None:
    d, c = state.get("device"), state.get("connectivity")
    out = _pick(d, ("uptime_s", "heap_free", "heap_min_free"))
    if out is None or not isinstance(c, dict):
        return None
    out["wifi_ok"] = c.get("wifi_state") == 2
    out["daemon_state"] = str(c.get("daemon_state", ""))[:32]
    return out


def _weather(state: dict) -> dict | None:
    e = _pick(state.get("env"), ("temp_c", "hi_c", "lo_c", "wcode", "loc", "valid"))
    au = _pick(state.get("aurora"), ("pct", "kp_x10", "cloud_pct", "night"))
    if not e or not e.pop("valid") or not au:
        return None
    return {**e, "loc": str(e["loc"])[:24], "aurora_pct": au["pct"], "kp_x10": au["kp_x10"],
            "cloud_pct": au["cloud_pct"], "night": au["night"]}


def _ci(state: dict) -> dict | None:
    c = _pick(state.get("ci"), ("state", "review", "total", "items"))
    if c is None:
        return None
    items = []
    for it in (c["items"] or [])[:4]:
        url = str(it.get("pr_url") or it.get("url") or "")
        items.append({
            "state": str(it.get("state", ""))[:16], "repo": str(it.get("repo", ""))[:80],
            "title": str(it.get("title", ""))[:120], "branch": str(it.get("branch", ""))[:80],
            "workflow": str(it.get("workflow", ""))[:80], "job": str(it.get("job", ""))[:80],
            "step": str(it.get("step", ""))[:80], "pr": int(it.get("pr") or 0),
            "url": url if url.startswith("https://github.com/") and len(url) <= 300 else "",
        })
    return {"state": str(c["state"])[:16], "review": c["review"], "total": c["total"], "items": items}


_SECTIONS: dict[str, Callable[[dict], dict | None]] = {
    "air": _air,
    "indoor": lambda s: _pick(s.get("indoor"), ("present", "temp_c", "pressure_hpa", "humidity_pct")),
    "claude": lambda s: _pick(s.get("claude"), ("session_pct", "session_reset_mins", "weekly_pct",
                                                "weekly_reset_mins", "status", "model", "ctx_pct", "valid")),
    "activity": lambda s: _pick(s.get("activity"), ("state", "agents")),
    "copilot": lambda s: _pick(s.get("copilot"), ("premium_pct", "premium_total", "premium_reset_str",
                                                  "plan", "valid")),
    "codex": lambda s: _pick(s.get("codex"), ("p1", "p2", "w1", "w2", "r1", "r2", "ts", "st", "plan", "valid")),
    "sysinfo": lambda s: _pick(s.get("sysinfo"), ("cpu_pct", "ram_pct", "disk_pct", "cpu_temp", "valid")),
    "today": lambda s: _pick(s.get("today"), ("active_min", "tok_k", "usd", "commits", "cp_used", "valid")),
    "device": _device,
    "weather": _weather,
    "ci": _ci,
    "vscode": lambda s: _pick(s.get("vscode"), ("mem_mb", "cpu_pct", "ext_count", "error_count")),
}


def parse_sections(raw: str) -> tuple[str, ...]:
    extra = tuple(x.strip().lower() for x in raw.split(",") if x.strip())
    unknown = [x for x in extra if x not in OPTIONAL_SECTIONS and x not in DEFAULT_SECTIONS]
    if unknown:
        raise ValueError(f"unknown cloud_sections: {', '.join(unknown)}")
    return DEFAULT_SECTIONS + tuple(x for x in extra if x in OPTIONAL_SECTIONS)


def build_snapshot(state: dict, sections: tuple[str, ...], now: int) -> dict:
    snap: dict = {"v": 1, "sent_at": now}
    for name in sections:
        part = _SECTIONS[name](state)
        if part is not None:
            snap[name] = part
    return snap


def sign(secret: str, ts: int, body: bytes) -> dict[str, str]:
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Clawd-Ts": str(ts), "X-Clawd-Sig": mac, "Content-Type": "application/json"}


def validate_url(url: str) -> str:
    u = urlparse(url)
    local = u.hostname in ("localhost", "127.0.0.1")
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise ValueError("cloud_url must be https:// (http only for localhost testing)")
    if not u.hostname:
        raise ValueError("cloud_url has no host")
    return url.rstrip("/")


class CloudPush:
    def __init__(self, url: str, secret: str, sections: tuple[str, ...],
                 log: Callable[[str], None] = print) -> None:
        self.url = validate_url(url) + "/api/ingest"
        if len(secret) < MIN_SECRET_LEN:
            raise ValueError(f"cloud_secret must be at least {MIN_SECRET_LEN} characters")
        self.secret = secret
        self.sections = sections
        self.log = log
        self.backoff = PUSH_INTERVAL

    @classmethod
    def from_config(cls, cfg: dict[str, str], log: Callable[[str], None] = print) -> "CloudPush | None":
        url = cfg.get("cloud_url", "").strip()
        if not url:
            return None
        try:
            return cls(url, cfg.get("cloud_secret", "").strip(),
                       parse_sections(cfg.get("cloud_sections", "")), log)
        except ValueError as e:
            log(f"Cloud push disabled: {e}")
            return None

    async def push_once(self, http: httpx.AsyncClient, state: dict) -> bool:
        ts = int(time.time())
        body = json.dumps(build_snapshot(state, self.sections, ts), separators=(",", ":")).encode()
        try:
            r = await http.post(self.url, content=body, headers=sign(self.secret, ts, body))
        except httpx.HTTPError as e:
            self.log(f"Cloud push failed: {e}")
            return False
        if r.status_code != 204:
            self.log(f"Cloud push rejected: HTTP {r.status_code} {r.text[:120]}")
            return False
        return True

    async def run(self, fetch_state: Callable[[], Awaitable[dict | None]],
                  stop_event: asyncio.Event) -> None:
        """Independent of the device-write loop: a slow or failing cloud never
        delays a payload to the device. Backs off to 15 min while failing."""
        self.log(f"Cloud push to {self.url} ({', '.join(self.sections)})")
        async with httpx.AsyncClient(timeout=15.0) as http:
            while not stop_event.is_set():
                state = await fetch_state()
                ok = state is not None and await self.push_once(http, state)
                self.backoff = PUSH_INTERVAL if ok else min(self.backoff * 2, MAX_BACKOFF)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.backoff)
                except asyncio.TimeoutError:
                    pass
