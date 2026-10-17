"""check_consistency.py passes on the real tree and catches each class of drift."""
import gzip
import shutil
import unittest
from unittest import mock

from _util import scratch_tree

import check_consistency as cc

FILES = ("firmware/src/ui.h", "firmware/src/ui.cpp", "firmware/src/device_config.cpp",
         "firmware/src/web_ui.h", "tools/web_ui/index.html", "tools/claudepix_data")


class RealTree(unittest.TestCase):
    def test_all_checks_pass_on_repo(self):
        for name, fn in cc.CHECKS.items():
            with self.subTest(check=name):
                self.assertEqual(fn(), [], f"{name} fails on the committed tree")


class DetectsDrift(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch_tree(*FILES)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        src, web = self.tmp / "firmware" / "src", self.tmp / "tools" / "web_ui" / "index.html"
        patches = [mock.patch.object(cc, "ROOT", self.tmp), mock.patch.object(cc, "SRC", src),
                   mock.patch.object(cc, "WEB", web)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.src, self.web = src, web

    def edit(self, path, old, new):
        s = path.read_text(encoding="utf-8")
        self.assertIn(old, s)
        path.write_text(s.replace(old, new, 1), encoding="utf-8")

    def test_cycle_order_mismatch(self):
        self.edit(self.src / "device_config.cpp", "SCREEN_CI, SCREEN_TODAY", "SCREEN_TODAY, SCREEN_CI")
        self.assertTrue(cc.check_cycle_order())

    def test_screen_dropped_from_cycle(self):
        for f in ("ui.cpp", "device_config.cpp"):
            self.edit(self.src / f, "SCREEN_CI, SCREEN_TODAY,", "SCREEN_TODAY,")
        errs = cc.check_cycle_order()
        self.assertTrue(any("SCREEN_CI" in e for e in errs), errs)

    def test_conn_bit_wrong(self):
        self.edit(self.src / "device_config.cpp", "(1u << 8)", "(1u << 7)")
        self.assertTrue(cc.check_required_bits())

    def test_new_enum_value_without_web_label(self):
        self.edit(self.src / "ui.h", "SCREEN_AURORA,", "SCREEN_AURORA,\n    SCREEN_NEW,")
        self.assertTrue(cc.check_screen_enum())

    def test_web_screen_names_out_of_order(self):
        self.edit(self.web, "'Splash', 'Clock'", "'Clock', 'Splash'")
        self.assertTrue(cc.check_web_screen_names())

    def test_web_cfg_label_wrong(self):
        self.edit(self.web, "{ bit: 9, label: 'Checks' }", "{ bit: 9, label: 'Today' }")
        self.assertTrue(cc.check_web_cfg_screens())

    def test_web_cfg_missing_bit(self):
        self.edit(self.web, "{ bit: 10, label: 'Today' },", "")
        self.assertTrue(cc.check_web_cfg_screens())

    def test_stale_web_ui_h(self):
        self.web.write_bytes(self.web.read_bytes() + b"<!-- edited -->")
        errs = cc.check_web_ui_fresh()
        self.assertTrue(any("stale" in e for e in errs), errs)

    def test_fresh_web_ui_h_roundtrip(self):
        # A header regenerated the way build_web_ui.js does it must pass.
        gz = gzip.compress(self.web.read_bytes())
        body = ",".join(f"0x{b:02x}" for b in gz)
        (self.src / "web_ui.h").write_text(
            f"static const uint8_t INDEX_HTML_GZ[] = {{{body}}};\n"
            f"static const size_t INDEX_HTML_GZ_LEN = {len(gz)};\n", encoding="utf-8")
        self.assertEqual(cc.check_web_ui_fresh(), [])

    def test_web_ui_fresh_ignores_line_endings(self):
        # core.autocrlf: the header may embed CRLF while the page on disk is
        # LF (or vice versa) -- same content, must not read as stale.
        lf = self.web.read_bytes().replace(b"\r\n", b"\n")
        gz = gzip.compress(lf.replace(b"\n", b"\r\n"))
        (self.src / "web_ui.h").write_text(
            "static const uint8_t INDEX_HTML_GZ[] = {" + ",".join(f"0x{b:02x}" for b in gz) + "};\n"
            f"static const size_t INDEX_HTML_GZ_LEN = {len(gz)};\n", encoding="utf-8")
        self.web.write_bytes(lf)
        self.assertEqual(cc.check_web_ui_fresh(), [])

    def test_unindexed_animation(self):
        d = self.tmp / "tools" / "claudepix_data"
        shutil.copy2(d / "copilot_idle.json", d / "new_anim.json")
        errs = cc.check_splash_index()
        self.assertTrue(any("new_anim" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
