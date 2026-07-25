#!/usr/bin/env python3
"""Claude Usage Tracker Daemon (BLE) — macOS port of claude-usage-daemon.sh.

Polls Claude API rate-limit headers and writes a JSON payload to the
ESP32 "Claude Controller" peripheral over a custom GATT service. Uses
bleak (CoreBluetooth backend on macOS).
"""

import asyncio
import getpass
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

DEVICE_NAME = "Claude Controller"
SERVICE_UUID = "4c41555a-4465-7669-6365-000000000001"
RX_CHAR_UUID = "4c41555a-4465-7669-6365-000000000002"
REQ_CHAR_UUID = "4c41555a-4465-7669-6365-000000000004"

POLL_INTERVAL = 60
COPILOT_POLL_INTERVAL = 300  # 5 minutes
SYSINFO_POLL_INTERVAL = 30   # 30 seconds
VSCODE_POLL_INTERVAL = 30    # 30 seconds
TICK = 5
SCAN_TIMEOUT = 8.0

# macOS: token lives in Keychain (service "Claude Code-credentials").
# Linux: token lives in ~/.claude/.credentials.json.
KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_CONFIG_DIR = Path.home() / ".claude"
CREDENTIALS_PATH = DEFAULT_CONFIG_DIR / ".credentials.json"
CONFIG_FILE = Path.home() / ".config" / "claude-usage-monitor" / "config"
SAVED_ADDR_FILE = Path.home() / ".config" / "claude-usage-monitor" / "ble-address"
TOKEN_ENV_VARS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY",
)

_missing_token_logged = False

API_URL = "https://api.anthropic.com/v1/messages"
API_HEADERS_TEMPLATE = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": "claude-code/2.1.5",
}
API_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_github_token() -> str | None:
    """Get GitHub auth token via `gh auth token` CLI."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                return token
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


async def poll_copilot(gh_token: str) -> dict | None:
    """Poll /copilot_internal/user for premium request quota.

    Returns quota_snapshots.premium_interactions (percent_remaining, remaining,
    entitlement) and quota_reset_date_utc. Works for individual Copilot Pro plan.
    """
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    result: dict = {
        "src": "copilot",
        "en": False,
        "plan": "unknown",
        "pp": -1,   # premium_pct_used (0-100)
        "pr": -1,   # premium_remaining
        "pe": -1,   # premium_entitlement (total)
        "prm": -1,  # minutes until quota reset
        "ok": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                "https://api.github.com/copilot_internal/user", headers=headers
            )
            if resp.status_code == 200:
                data = resp.json()
                result["en"] = True
                plan_raw = data.get("copilot_plan", "individual").lower()
                _plan_map = {
                    "individual": "Pro", "pro": "Pro", "copilot_pro": "Pro",
                    "business": "Business", "enterprise": "Enterprise",
                }
                result["plan"] = _plan_map.get(plan_raw, plan_raw.title())

                # premium_interactions quota
                pi = (data.get("quota_snapshots") or {}).get("premium_interactions") or {}
                pct_rem = pi.get("percent_remaining", -1)
                if pct_rem >= 0:
                    result["pp"] = int(round(100 - pct_rem))
                remaining = pi.get("remaining", -1)
                if isinstance(remaining, (int, float)) and remaining >= 0:
                    result["pr"] = int(remaining)
                entitlement = pi.get("entitlement", -1)
                if isinstance(entitlement, (int, float)) and entitlement > 0:
                    result["pe"] = int(entitlement)

                # Minutes until monthly reset
                reset_date = data.get("quota_reset_date_utc") or data.get("quota_reset_date")
                if reset_date:
                    try:
                        if "T" in reset_date:
                            reset_dt = datetime.fromisoformat(reset_date.replace("Z", "+00:00"))
                        else:
                            reset_dt = datetime.fromisoformat(reset_date + "T00:00:00+00:00")
                        mins = int((reset_dt - datetime.now(timezone.utc)).total_seconds() / 60)
                        result["prm"] = max(0, mins)
                        local_dt = reset_dt.astimezone()
                        result["prd"] = local_dt.strftime("%b ") + str(local_dt.day)
                    except Exception:
                        pass
            elif resp.status_code == 404:
                log("Copilot: /copilot_internal/user returned 404")
    except httpx.HTTPError as e:
        log(f"Copilot API error: {e}")
        result["ok"] = False
    log(
        f"Copilot: plan={result['plan']} enabled={result['en']} "
        f"premium={result['pp']}% remaining={result['pr']}/{result['pe']} reset_mins={result['prm']}"
    )
    return result


def poll_sysinfo() -> dict:
    """Collect CPU, RAM, and disk stats via psutil.

    Returns a dict ready to send as a BLE JSON payload with src='sysinfo'.
    All fields fall back to -1 / 0.0 when unavailable (e.g. no sensor data on macOS).
    """
    result: dict = {
        "src": "sysinfo",
        "cpu": -1,   # CPU utilization 0-100
        "ct": -1.0,  # CPU temperature °C
        "rp": -1,    # RAM used %
        "ru": 0.0,   # RAM used GB
        "rt": 0.0,   # RAM total GB
        "dp": -1,    # Disk used %
        "du": 0.0,   # Disk used GB
        "dt": 0.0,   # Disk total GB
    }
    try:
        import psutil  # type: ignore[import-untyped]

        result["cpu"] = int(psutil.cpu_percent(interval=None))

        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Prefer coretemp / k10temp / cpu_thermal; fall back to first entry
                for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                    if key in temps and temps[key]:
                        result["ct"] = round(temps[key][0].current, 1)
                        break
                else:
                    first_group = next(iter(temps.values()))
                    if first_group:
                        result["ct"] = round(first_group[0].current, 1)
        except (AttributeError, OSError):
            pass  # macOS: sensors_temperatures() not available

        vm = psutil.virtual_memory()
        result["rp"] = int(vm.percent)
        result["ru"] = round(vm.used / 1e9, 1)
        result["rt"] = round(vm.total / 1e9, 1)

        disk_path = (os.getenv('SystemDrive', 'C:') + os.sep) if sys.platform.startswith('win') else '/'
        du = psutil.disk_usage(disk_path)
        result["dp"] = int(du.percent)
        result["du"] = round(du.used / 1e9, 0)
        result["dt"] = round(du.total / 1e9, 0)

        log(
            f"Sysinfo: cpu={result['cpu']}% temp={result['ct']}°C "
            f"ram={result['rp']}% ({result['ru']}/{result['rt']} GB) "
            f"disk={result['dp']}% ({result['du']}/{result['dt']} GB)"
        )
    except ImportError:
        if not getattr(poll_sysinfo, "_missing_logged", False):
            log("psutil not installed; skipping sysinfo poll (pip install psutil)")
            setattr(poll_sysinfo, "_missing_logged", True)
    except Exception as exc:
        log(f"Sysinfo poll error: {exc}")

    return result


def poll_vscode() -> dict:
    """Collect VS Code process stats and recent log errors.

    Aggregates all Code/code processes for memory and CPU, counts extension
    hosts, and scans VS Code log files for errors/criticals in the last 30 min.
    Returns a dict with src='vscode' ready to send as a BLE JSON payload.
    """
    import re as _re

    result: dict = {
        "src": "vscode",
        "mm": -1,   # total RSS in MB
        "vc": -1,   # total CPU %
        "xe": -1,   # extension host process count
        "ec": -1,   # error count (last 30 min)
        "le": "",   # last error snippet
    }

    # --- Process stats via psutil ---
    try:
        import psutil  # type: ignore[import-untyped]

        vscode_procs = []
        ext_hosts = 0
        for proc in psutil.process_iter(["name", "cmdline", "memory_info", "cpu_percent", "status"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if name in ("code.exe", "code", "code-insiders", "code-insiders.exe") or \
                        "visual studio code" in cmdline or \
                        ("/code/" in cmdline and "electron" in cmdline):
                    vscode_procs.append(proc)
                    if "extensionhost" in name or "extensionhost" in cmdline:
                        ext_hosts += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if vscode_procs:
            total_rss = sum(
                p.info["memory_info"].rss for p in vscode_procs
                if p.info.get("memory_info")
            )
            total_cpu = sum(
                p.info["cpu_percent"] or 0 for p in vscode_procs
            )
            result["mm"] = int(total_rss / 1e6)
            result["vc"] = int(round(total_cpu))
            result["xe"] = ext_hosts

    except ImportError:
        log("psutil not installed; skipping vscode poll (pip install psutil)")
    except Exception as exc:
        log(f"VS Code process poll error: {exc}")

    # --- Log scan for errors in last 30 min ---
    try:
        log_roots = []
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                log_roots.append(Path(appdata) / "Code" / "logs")
                log_roots.append(Path(appdata) / "Code - Insiders" / "logs")
        elif sys.platform == "darwin":
            log_roots.append(Path.home() / "Library" / "Application Support" / "Code" / "logs")
        else:
            log_roots.append(Path.home() / ".config" / "Code" / "logs")

        cutoff = time.time() - 1800  # 30 minutes
        error_pat = _re.compile(r"\[error\]|\[critical\]", _re.IGNORECASE)
        error_count = 0
        last_error = ""

        for log_root in log_roots:
            if not log_root.exists():
                continue
            # Find all .log files modified in the last 30 min
            for log_file in sorted(log_root.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    if log_file.stat().st_mtime < cutoff:
                        continue
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if error_pat.search(line):
                                error_count += 1
                                # Keep last error as a short snippet
                                snippet = line.strip()
                                # Strip timestamp prefix like "[2024-01-01 12:00:00.000] "
                                snippet = _re.sub(r"^\[[\d\-T :\.Z]+\]\s*", "", snippet)
                                snippet = _re.sub(r"\[(?:error|critical)\]\s*", "", snippet, flags=_re.IGNORECASE)
                                last_error = snippet[:28]
                except (OSError, PermissionError):
                    continue

        result["ec"] = error_count
        result["le"] = last_error

    except Exception as exc:
        log(f"VS Code log scan error: {exc}")
        result["ec"] = 0

    log(
        f"VS Code: mem={result['mm']}MB cpu={result['vc']}% "
        f"ext_hosts={result['xe']} errors={result['ec']}"
    )
    return result



def _extract_access_token(blob: str) -> str | None:
    """Pull the accessToken out of a credentials blob.

    Claude Code stores credentials as a JSON object; the blob may also be
    nested ({"claudeAiOauth": {"accessToken": "..."}}). Fall back to a
    regex match so unexpected shapes still work, and finally treat the
    blob as a raw token if nothing else matches.
    """
    blob = blob.strip()
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, (dict, list)):
        # Recursively search nested JSON for a non-empty accessToken.
        def walk(node: object) -> str | None:
            if isinstance(node, dict):
                v = node.get("accessToken")
                if isinstance(v, str):
                    t = v.strip()
                    if t:
                        return t
                for child in node.values():
                    hit = walk(child)
                    if hit:
                        return hit
            elif isinstance(node, list):
                for child in node:
                    hit = walk(child)
                    if hit:
                        return hit
            return None

        token = walk(data)
        if token:
            return token
    m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1)
    # Raw token (no JSON wrapper) — must look plausible (sk-ant-... etc.)
    if re.fullmatch(r"[A-Za-z0-9_\-.~+/=]{20,}", blob):
        return blob
    return None


def _read_token_keychain() -> str | None:
    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                getpass.getuser(),
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        log(f"Keychain read failed (rc={e.returncode}): {e.stderr.strip()}")
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"Keychain access error: {e}")
        return None
    return _extract_access_token(out.stdout)


def read_config_dirs() -> list[Path]:
    """Claude config dirs from config_dirs in daemon config (comma-separated).

    Defaults to [~/.claude] when unset.
    """
    raw = ""
    try:
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == "config_dirs":
                    raw = val.strip()
    except OSError:
        pass

    if not raw:
        return [DEFAULT_CONFIG_DIR]

    dirs = [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]
    return dirs or [DEFAULT_CONFIG_DIR]


def _read_token_file(config_dir: Path) -> str | None:
    cred_file = config_dir / ".credentials.json"
    try:
        raw = cred_file.read_text(encoding="utf-8")
    except OSError as e:
        log(f"Error reading credentials in {config_dir}: {e}")
        return None
    return _extract_access_token(raw)


def _read_token_env() -> str | None:
    for env_name in TOKEN_ENV_VARS:
        val = os.getenv(env_name, "").strip()
        if val:
            return val
    return None


def read_token_for(config_dir: Path) -> str | None:
    token = _read_token_env()
    if token:
        return token

    token = _read_token_file(config_dir)
    if token:
        return token

    # Preserve the original macOS behavior: default profile can come from
    # Keychain with no on-disk token file.
    if sys.platform == "darwin" and config_dir == DEFAULT_CONFIG_DIR:
        return _read_token_keychain()

    return None


def read_token() -> str | None:
    global _missing_token_logged

    # Keep this helper for compatibility; first non-empty token wins.
    for cfg_dir in read_config_dirs():
        token = read_token_for(cfg_dir)
        if token:
            return token

    if not _missing_token_logged:
        log(
            "No Claude OAuth token found. Expected a non-empty accessToken in "
            "<config_dir>/.credentials.json for config_dirs from "
            f"{CONFIG_FILE} (default {DEFAULT_CONFIG_DIR}) or one of "
            f"{', '.join(TOKEN_ENV_VARS)}"
        )
        _missing_token_logged = True
    return None


async def poll_active_payload() -> dict | None:
    """Poll configured Claude config dirs and return the first valid payload."""
    for cfg_dir in read_config_dirs():
        token = read_token_for(cfg_dir)
        if not token:
            continue
        payload = await poll_api(token)
        if payload is not None:
            return payload
    return None


def load_cached_address() -> str | None:
    if not SAVED_ADDR_FILE.exists():
        return None
    addr = SAVED_ADDR_FILE.read_text().strip()
    # Accept both Linux MAC (AA:BB:CC:DD:EE:FF) and macOS CoreBluetooth UUID
    # (E621E1F8-C36C-495A-93FC-0C247A3E6E5F).
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", addr) or re.fullmatch(
        r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}", addr
    ):
        return addr
    log("Cached address malformed, discarding")
    SAVED_ADDR_FILE.unlink(missing_ok=True)
    return None


def save_address(addr: str) -> None:
    SAVED_ADDR_FILE.parent.mkdir(parents=True, exist_ok=True)
    SAVED_ADDR_FILE.write_text(addr)


async def scan_for_device() -> str | None:
    log(f"Scanning for '{DEVICE_NAME}' ({SCAN_TIMEOUT}s)...")
    devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)
    for d in devices:
        if d.name == DEVICE_NAME:
            log(f"Found: {d.address}")
            return d.address
    return None


async def poll_api(token: str) -> dict | None:
    headers = dict(API_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(API_URL, headers=headers, json=API_BODY)
    except httpx.HTTPError as e:
        log(f"API call failed: {e}")
        return None

    def hdr(name: str, default: str = "0") -> str:
        return resp.headers.get(name, default)

    # Even on 429/other non-2xx, Anthropic returns ratelimit headers that are
    # sufficient to render usage + reset timers on-device. Keep using them.
    s5h_u = hdr("anthropic-ratelimit-unified-5h-utilization", "")
    s5h_r = hdr("anthropic-ratelimit-unified-5h-reset", "")
    s7d_u = hdr("anthropic-ratelimit-unified-7d-utilization", "")
    s7d_r = hdr("anthropic-ratelimit-unified-7d-reset", "")
    if resp.status_code >= 400:
        log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        if not (s5h_u and s5h_r and s7d_u and s7d_r):
            return None

    now = time.time()

    def reset_minutes(reset_ts: str) -> int:
        try:
            r = float(reset_ts)
        except ValueError:
            return 0
        mins = (r - now) / 60.0
        return int(round(mins)) if mins > 0 else 0

    def pct(util: str) -> int:
        try:
            return int(round(float(util) * 100))
        except ValueError:
            return 0

    payload = {
        "s": pct(s5h_u),
        "sr": reset_minutes(s5h_r),
        "w": pct(s7d_u),
        "wr": reset_minutes(s7d_r),
        "st": hdr("anthropic-ratelimit-unified-5h-status", "unknown"),
        "ok": resp.status_code < 400,
    }
    return payload


class Session:
    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.refresh_requested = asyncio.Event()

    def _on_refresh(self, _char, _data: bytearray) -> None:
        log("Refresh requested by device")
        self.refresh_requested.set()

    async def setup_refresh_subscription(self) -> None:
        try:
            await self.client.start_notify(REQ_CHAR_UUID, self._on_refresh)
        except (BleakError, ValueError) as e:
            log(f"Refresh subscription unavailable: {e}")

    async def write_payload(self, payload: dict) -> bool:
        data = json.dumps(payload, separators=(",", ":")).encode()
        log(f"Sending: {data.decode()}")

        # Double‑check connection before writing
        if not self.client.is_connected:
            log("❌ BLE client not connected – cannot write")
            return False

        try:
            await self.client.write_gatt_char(RX_CHAR_UUID, data, response=False)
            return True
        except BleakError as e:
            log(f"Write failed: {e}")
            return False


async def connect_and_run(address: str, stop_event: asyncio.Event) -> bool:
    """Connect to a known address and poll until disconnected or stopped.

    Returns True if the connection was used successfully (so the caller
    keeps the cached address), False if the connection failed and the
    cache should be invalidated.
    """
    log(f"Connecting to {address}...")
    client = BleakClient(address)
    try:
        await client.connect()
    except (BleakError, asyncio.TimeoutError) as e:
        log(f"Connection failed: {e}")
        return False

    if not client.is_connected:
        log("Connection failed (no error but not connected)")
        return False

    log("Connected")
    session = Session(client)
    await session.setup_refresh_subscription()

    last_poll = 0.0
    last_copilot_poll = 0.0
    last_sysinfo_poll = 0.0
    last_vscode_poll = 0.0
    used_successfully = False

    # Warm up cpu_percent so the first non-blocking call returns a real value
    try:
        import psutil  # type: ignore[import-untyped]
        psutil.cpu_percent(interval=None)
    except ImportError:
        pass

    try:
        while client.is_connected and not stop_event.is_set():
            now = time.time()
            elapsed = now - last_poll
            if session.refresh_requested.is_set() or elapsed >= POLL_INTERVAL:
                session.refresh_requested.clear()
                payload = await poll_active_payload()
                if payload is None:
                    log("No Claude payload; skipping poll")
                elif await session.write_payload(payload):
                    last_poll = time.time()
                    used_successfully = True

            try:
                await asyncio.wait_for(session.refresh_requested.wait(), timeout=TICK)
            except asyncio.TimeoutError:
                pass

            # GitHub Copilot poll every 5 minutes
            now = time.time()
            if now - last_copilot_poll >= COPILOT_POLL_INTERVAL:
                last_copilot_poll = now
                gh_token = read_github_token()
                if gh_token:
                    cp_payload = await poll_copilot(gh_token)
                    if cp_payload is not None:
                        await session.write_payload(cp_payload)
                else:
                    log("No GitHub token (install gh CLI and run 'gh auth login'); skipping Copilot poll")

            # System info poll every 30 seconds
            now = time.time()
            if now - last_sysinfo_poll >= SYSINFO_POLL_INTERVAL:
                last_sysinfo_poll = now
                si_payload = poll_sysinfo()
                await session.write_payload(si_payload)

            # VS Code stats poll every 30 seconds
            now = time.time()
            if now - last_vscode_poll >= VSCODE_POLL_INTERVAL:
                last_vscode_poll = now
                vs_payload = poll_vscode()
                await session.write_payload(vs_payload)
    finally:
        try:
            await client.disconnect()
        except BleakError:
            pass

    log("Device disconnected" if not stop_event.is_set() else "Stopping")
    return used_successfully


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop(*_args: object) -> None:
        log("Daemon stopping")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, _stop)

    log("=== Claude Usage Tracker Daemon (BLE) ===")
    log(f"Poll interval: {POLL_INTERVAL}s")

    backoff = 1
    while not stop_event.is_set():
        address = load_cached_address()
        if not address:
            address = await scan_for_device()
            if address:
                save_address(address)
            else:
                log(f"Device not found, retrying in {backoff}s...")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)
                continue

        ok = await connect_and_run(address, stop_event)
        if not ok:
            log("Invalidating cached address")
            SAVED_ADDR_FILE.unlink(missing_ok=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)
        else:
            backoff = 1


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
