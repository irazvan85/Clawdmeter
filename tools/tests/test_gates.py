"""Gate logic for resource_report.py, perf_check.py and the existing
check_auth_gated_routes.py -- each must actually fail when it should."""
import contextlib
import io
import shutil
import unittest
from unittest import mock

from _util import scratch_tree

import check_auth_gated_routes as auth
import perf_check
import resource_report as rr

BASE = {"static_dram": 60_000, "iram": 86_000, "app_bin": 1_700_000}


def metrics(**over):
    m = {"static_dram": 60_000, "iram": 86_000, "app_bin": 1_700_000,
         "app_partition": 4_063_232, "dram_data": 0, "dram_bss": 0,
         "flash_text": 0, "flash_rodata": 0, "top": {"dram": [], "flash": []}}
    m.update(over)
    return m


class ResourceGates(unittest.TestCase):
    def test_within_budget(self):
        self.assertEqual(rr.evaluate(metrics(), BASE), [])

    def test_static_dram_growth(self):
        fails = rr.evaluate(metrics(static_dram=70_000), BASE)    # +16.7%
        self.assertTrue(any("static_dram" in f for f in fails), fails)

    def test_app_partition_nearly_full(self):
        fails = rr.evaluate(metrics(app_bin=3_800_000), None)
        self.assertTrue(any("app partition" in f for f in fails), fails)

    def test_iram_nearly_full(self):
        self.assertTrue(rr.evaluate(metrics(iram=128_000), None))

    def test_no_baseline_only_absolute_gates(self):
        self.assertEqual(rr.evaluate(metrics(static_dram=200_000), None), [])

    def test_partition_parse(self):
        self.assertEqual(rr.app_partition_size(), 0x3E0000)

    def test_render_ascii(self):
        md = rr.render(metrics(), BASE, [])
        self.assertTrue(md.isascii(), "report must survive a cp1252 console (gotcha #10)")


class PerfGates(unittest.TestCase):
    def verdict(self, key, value):
        r = perf_check.Results()
        r.gate("s", "m", value, key)
        return r.rows[-1][3]

    def test_low_heap_fails(self):
        self.assertEqual(self.verdict("max_alloc_min", 20_000), "FAIL")
        self.assertEqual(self.verdict("max_alloc_min", 40_000), "warn")
        self.assertEqual(self.verdict("max_alloc_min", 80_000), "ok")

    def test_slow_lvgl_fails(self):
        self.assertEqual(self.verdict("lv_max_us", 2_000_000), "FAIL")
        self.assertEqual(self.verdict("lv_max_us", 50_000), "ok")

    def test_info_rows_never_fail(self):
        r = perf_check.Results()
        r.gate("s", "m", 1)
        self.assertEqual((r.fails, r.warns), (0, 0))


class AuthRouteGuard(unittest.TestCase):
    """The static guard must still flag the screenshot-auth regression it was
    written for (CLAUDE.md, 2026-09-17 security review)."""

    def test_passes_on_repo(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.main(), 0)

    def test_flags_ungated_route(self):
        tmp = scratch_tree("firmware/src/web_server.cpp")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "firmware" / "src" / "web_server.cpp"
        s = path.read_text(encoding="utf-8")
        start = s.index("static void handle_screenshot(")
        body_end = s.index("\n}\n", start)
        gated = s[start:body_end]
        self.assertIn("wifi_get_token()", gated)
        path.write_text(s[:start] + gated.replace("wifi_get_token()", "\"\"") + s[body_end:],
                        encoding="utf-8")
        with mock.patch.object(auth, "SRC_PATH", path), contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(auth.main(), 0)


if __name__ == "__main__":
    unittest.main()
