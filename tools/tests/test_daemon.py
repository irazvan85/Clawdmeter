"""Pure-function tests for daemon/claude_usage_daemon.py. Skipped when httpx
(the daemon's one third-party import) isn't installed -- e.g. under
PlatformIO's penv python during the pre-upload gate."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _util  # noqa: F401  (sets sys.path)

try:
    import claude_usage_daemon as d
except ImportError as e:     # httpx missing
    d = None
    SKIP = f"daemon not importable: {e}"
else:
    SKIP = ""


@unittest.skipIf(d is None, SKIP)
class RememberPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.file = self.tmp / "last-payloads.json"
        for p in (mock.patch.object(d, "LAST_PAYLOAD_FILE", self.file),
                  mock.patch.object(d, "_last_payloads", {})):
            p.start()
            self.addCleanup(p.stop)

    def test_wifi_never_cached(self):
        # Regression: a cached {"src":"wifi",...} once sat in this file in
        # plaintext and would have been replayed on every reconnect.
        d.remember_payload({"src": "wifi", "ssid": "x", "pass": "secret"})
        self.assertFalse(self.file.exists() and "secret" in self.file.read_text())

    def test_transient_srcs_not_cached(self):
        d.remember_payload({"src": "status", "state": "ok"})
        d.remember_payload({"src": "act", "st": "idle"})
        self.assertEqual(d._last_payloads, {})

    def test_regular_payload_cached_and_default_src(self):
        d.remember_payload({"s": 10})
        d.remember_payload({"src": "ci", "state": "pass"})
        self.assertEqual(set(json.loads(self.file.read_text())), {"claude", "ci"})

    def test_load_drops_legacy_wifi_entry(self):
        self.file.write_text(json.dumps({"wifi": {"pass": "secret"}, "ci": {"state": "pass"}}))
        d.load_last_payloads()
        self.assertEqual(set(d._last_payloads), {"ci"})


@unittest.skipIf(d is None, SKIP)
class Helpers(unittest.TestCase):
    def test_extract_access_token_shapes(self):
        tok = "sk-ant-oat01-" + "a" * 30
        self.assertEqual(d._extract_access_token(json.dumps({"claudeAiOauth": {"accessToken": tok}})), tok)
        self.assertEqual(d._extract_access_token(json.dumps([{"x": {"accessToken": tok}}])), tok)
        self.assertEqual(d._extract_access_token(tok), tok)
        self.assertIsNone(d._extract_access_token(""))
        self.assertIsNone(d._extract_access_token("not a token"))

    def test_model_short(self):
        self.assertEqual(d._model_short("claude-opus-5-5"), "Opus")
        self.assertEqual(d._model_short("claude-haiku-4-5-20251001"), "Haiku")
        self.assertEqual(d._model_short(""), "")

    def test_ascii_folds_for_device_fonts(self):
        self.assertTrue(d._ascii("Timișoara").isascii())

    def test_solar_altitude_day_night(self):
        # Bucharest: high sun at local noon in June, below horizon at midnight UTC.
        noon = d._solar_altitude_deg(44.43, 26.10, datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc))
        night = d._solar_altitude_deg(44.43, 26.10, datetime(2026, 6, 21, 23, 0, tzinfo=timezone.utc))
        self.assertGreater(noon, 60)
        self.assertLess(night, 0)

    def test_status_payload_shape(self):
        self.assertEqual(d.status_payload("ok"), {"src": "status", "state": "ok"})


if __name__ == "__main__":
    unittest.main()
