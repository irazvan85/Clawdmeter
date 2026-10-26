"""Read Codex quotas through the local app-server; credentials stay with Codex.

Protocol: https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt
"""
import asyncio
import contextlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time


POLL_SECONDS = 60
STALE_SECONDS = 180


def find_codex(override: str = "") -> str | None:
    if override:
        return str(Path(override).expanduser())
    exe = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if exe:
        return exe
    # Scheduled Tasks may not inherit VS Code's extension-added PATH.
    if os.name == "nt":
        candidates = list((Path.home() / ".vscode/extensions").glob(
            "openai.chatgpt-*/bin/windows-x86_64/codex.exe"))
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    return None


def _number(value, default, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return value if math.isfinite(value) and value >= minimum else default


def _text(value, length):
    return str(value or "").encode("ascii", "replace").decode()[:length]


def normalize_limits(result: dict, bucket: str = "codex", now: int | None = None) -> dict:
    """Never merge independent limit buckets or invent percentages for absent windows."""
    mapped = result.get("rateLimitsByLimitId") or {}
    limit = mapped.get(bucket) if isinstance(mapped, dict) else None
    legacy = result.get("rateLimits")
    if not isinstance(limit, dict) and isinstance(legacy, dict) and legacy.get("limitId") in (None, bucket):
        limit = legacy
    limit = limit if isinstance(limit, dict) else {}
    payload = {"src": "codex", "bucket": _text(bucket, 31), "plan": _text(limit.get("planType"), 23),
               "st": "unavailable", "ts": 0, "age": 0}
    for i, name in enumerate(("primary", "secondary"), 1):
        window = limit.get(name)
        window = window if isinstance(window, dict) else {}
        pct = _number(window.get("usedPercent"), -1)
        payload[f"p{i}"] = pct if pct <= 100 else -1
        payload[f"w{i}"] = int(_number(window.get("windowDurationMins"), 0, 1))
        payload[f"r{i}"] = int(_number(window.get("resetsAt"), 0, 1))
    if payload["p1"] >= 0 or payload["p2"] >= 0:
        payload.update(st="ok", ts=int(time.time()) if now is None else now)
    return payload


def age_payload(payload: dict, now: int | None = None) -> dict:
    """Also used on cache replay so old quotas retain their actual age/reset times."""
    result = dict(payload)
    ts = result.get("ts", 0)
    result["age"] = max(0, (int(time.time()) if now is None else now) - ts) if ts else 0
    if ts and result["age"] >= STALE_SECONDS and result.get("st") == "ok":
        result["st"] = "stale"
    return result


class RpcError(RuntimeError):
    def __init__(self, error):
        message = str(error.get("message", "")).lower()
        self.status = "sign_in" if any(x in message for x in ("not logged", "unauthorized", "authentication required")) else "unavailable"
        super().__init__("Codex quota request failed")


class CodexUsage:
    def __init__(self, executable: str = "", bucket: str = "codex", poll_seconds: float = POLL_SECONDS):
        self.executable = executable
        self.bucket = bucket
        self.poll_seconds = poll_seconds
        self.process = None
        self.reader = None
        self.pending = {}
        self.sequence = 0
        self.changed = asyncio.Event()
        self.reader_error = None
        self.good = None
        self.latest = normalize_limits({}, bucket)
        self.failures = 0

    def accept(self, result):
        single = result.get("rateLimits")
        mapped = result.get("rateLimitsByLimitId") or {}
        if isinstance(single, dict) and single.get("limitId") not in (None, self.bucket) and self.bucket not in mapped:
            return
        payload = normalize_limits(result, self.bucket)
        if payload["st"] == "ok":
            self.good = payload
            self.failures = 0
        elif self.good:
            payload = {**self.good, "st": "stale"}
        self.latest = payload
        self.changed.set()

    def failed(self, status):
        self.latest = {**self.good, "st": "stale"} if self.good else {
            **normalize_limits({}, self.bucket), "st": status}

    async def _send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Codex app-server closed")
                message = json.loads(line)
                future = self.pending.get(message.get("id"))
                if future is not None and not future.done() and ("result" in message or "error" in message):
                    if "error" in message:
                        future.set_exception(RpcError(message["error"]))
                    elif "result" in message:
                        future.set_result(message["result"])
                elif message.get("method") == "account/rateLimits/updated":
                    self.accept(message.get("params") or {})
                elif "method" in message and "id" in message:
                    await self._send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported request"}})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.reader_error = error
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Codex connection closed"))
            self.changed.set()

    async def rpc(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._send({"id": request_id, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, 20)
        finally:
            self.pending.pop(request_id, None)

    async def close(self):
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
            self.reader = None
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
                await self.process.wait()
            self.process = None

    async def run(self, publish, stop):
        try:
            while not stop.is_set():
                try:
                    executable = find_codex(self.executable)
                    if not executable:
                        raise FileNotFoundError("Codex not installed")
                    self.reader_error = None
                    self.changed.clear()
                    self.process = await asyncio.create_subprocess_exec(
                        executable, "app-server", "--listen", "stdio://",
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL, limit=262144,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    self.reader = asyncio.create_task(self._read())
                    await self.rpc("initialize", {"clientInfo": {"name": "clawdmeter", "title": "Clawdmeter", "version": "0.1.0"}})
                    await self._send({"method": "initialized", "params": {}})
                    self.accept(await self.rpc("account/rateLimits/read"))
                    next_poll = time.monotonic() + self.poll_seconds
                    last_push = 0.0
                    while not stop.is_set():
                        if self.reader_error:
                            raise RuntimeError("Codex connection closed")
                        if self.changed.is_set():
                            self.changed.clear()
                            # Coalesce bursts of notifications without blocking the RPC reader.
                            await asyncio.sleep(max(0, 2 - (time.monotonic() - last_push)))
                            await publish(age_payload(self.latest))
                            last_push = time.monotonic()
                        remaining = next_poll - time.monotonic()
                        if remaining <= 0:
                            self.accept(await self.rpc("account/rateLimits/read"))
                            next_poll = time.monotonic() + self.poll_seconds
                            continue
                        try:
                            await asyncio.wait_for(self.changed.wait(), min(remaining, 1))
                        except asyncio.TimeoutError:
                            pass
                except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as error:
                    self.failed("missing" if isinstance(error, FileNotFoundError) else
                                error.status if isinstance(error, RpcError) else "unavailable")
                    await publish(age_payload(self.latest))
                    self.failures += 1
                finally:
                    await self.close()
                try:
                    await asyncio.wait_for(stop.wait(), min(60, 5 * 2 ** min(self.failures, 4)))
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.close()
