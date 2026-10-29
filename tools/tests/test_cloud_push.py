"""daemon/cloud_push.py: allowlist filtering, signing, config validation.

tools/fixtures/cloud_snapshot.json is build_snapshot() applied to
tools/fixtures/device_state.json with every section on; the cloud app's
vitest suite validates that same file against its zod schema, so the two
sides of the ingest contract can't drift apart unnoticed.
"""
import asyncio
import hashlib
import hmac
import json
import unittest
from pathlib import Path

import _util  # noqa: F401

try:
    import cloud_push as cp
except ImportError as e:     # httpx missing
    cp = None
    SKIP = f"cloud_push not importable: {e}"
else:
    SKIP = ""

FIX = Path(__file__).resolve().parents[1] / "fixtures"
STATE = json.loads((FIX / "device_state.json").read_text(encoding="utf-8"))
SECRET = "s" * 40


@unittest.skipIf(cp is None, SKIP)
class Snapshot(unittest.TestCase):
    def test_fixture_is_current(self):
        snap = cp.build_snapshot(STATE, cp.DEFAULT_SECTIONS + cp.OPTIONAL_SECTIONS, 1793000000)
        self.assertEqual(snap, json.loads((FIX / "cloud_snapshot.json").read_text(encoding="utf-8")),
                         "regenerate tools/fixtures/cloud_snapshot.json")

    def test_defaults_exclude_opt_in_sections(self):
        snap = cp.build_snapshot(STATE, cp.parse_sections(""), 1)
        for s in ("weather", "ci", "vscode"):
            self.assertNotIn(s, snap)
        for s in cp.DEFAULT_SECTIONS:
            self.assertIn(s, snap)

    def test_never_sends_secrets_or_identifiers(self):
        blob = json.dumps(cp.build_snapshot(STATE, cp.DEFAULT_SECTIONS + cp.OPTIONAL_SECTIONS, 1))
        for needle in ("192.0.2.10", "wifi_ip", "secret/path", "last_error", "token", "sha", "abc1234"):
            self.assertNotIn(needle, blob)

    def test_only_github_https_links(self):
        items = cp.build_snapshot(STATE, ("ci",), 1)["ci"]["items"]
        self.assertEqual(items[0]["url"], "https://github.com/example/repo/pull/12")
        self.assertEqual(items[1]["url"], "")  # javascript: dropped

    def test_old_firmware_section_skipped_not_partial(self):
        state = {k: v for k, v in STATE.items() if k != "indoor"}
        state["air"] = {"present": True}  # missing fields
        snap = cp.build_snapshot(state, cp.DEFAULT_SECTIONS, 1)
        self.assertNotIn("indoor", snap)
        self.assertNotIn("air", snap)

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            cp.parse_sections("weather, everything")


@unittest.skipIf(cp is None, SKIP)
class Signing(unittest.TestCase):
    def test_matches_server_scheme(self):
        body = b'{"v":1}'
        h = cp.sign(SECRET, 1700000000, body)
        want = hmac.new(SECRET.encode(), b"1700000000." + body, hashlib.sha256).hexdigest()
        self.assertEqual((h["X-Clawd-Ts"], h["X-Clawd-Sig"]), ("1700000000", want))


@unittest.skipIf(cp is None, SKIP)
class Config(unittest.TestCase):
    def test_disabled_without_url(self):
        self.assertIsNone(cp.CloudPush.from_config({}, log=lambda m: None))

    def test_rejects_plain_http_and_short_secret(self):
        logs = []
        self.assertIsNone(cp.CloudPush.from_config(
            {"cloud_url": "http://example.com", "cloud_secret": SECRET}, log=logs.append))
        self.assertIsNone(cp.CloudPush.from_config(
            {"cloud_url": "https://x.vercel.app", "cloud_secret": "short"}, log=logs.append))
        self.assertEqual(len(logs), 2)

    def test_https_and_localhost_ok(self):
        p = cp.CloudPush.from_config({"cloud_url": "https://x.vercel.app/", "cloud_secret": SECRET},
                                     log=lambda m: None)
        self.assertEqual(p.url, "https://x.vercel.app/api/ingest")
        self.assertIsNotNone(cp.CloudPush.from_config(
            {"cloud_url": "http://localhost:3000", "cloud_secret": SECRET}, log=lambda m: None))


@unittest.skipIf(cp is None, SKIP)
class Backoff(unittest.TestCase):
    def test_backs_off_when_state_unavailable(self):
        p = cp.CloudPush("https://x.vercel.app", SECRET, cp.DEFAULT_SECTIONS, log=lambda m: None)
        stop = asyncio.Event()
        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            if calls >= 3:
                stop.set()
            return None

        async def go():
            orig = asyncio.wait_for

            async def fast(aw, timeout):  # don't actually sleep
                return await orig(aw, timeout=0.001)
            cp.asyncio.wait_for = fast
            try:
                await p.run(fetch, stop)
            finally:
                cp.asyncio.wait_for = orig
        asyncio.run(go())
        self.assertEqual(p.backoff, cp.PUSH_INTERVAL * 8)  # three failures: 60 -> 120 -> 240 -> 480


if __name__ == "__main__":
    unittest.main()
