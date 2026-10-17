"""Daemon <-> firmware payload contract.

Parses firmware/src/main.cpp's process_payload() into {src: {keys it reads}}
and checks tools/fixtures/payloads.json against it -- every fixture key must
be one the firmware actually reads (catches a renamed key on either side),
and every key the firmware reads must be covered by a fixture (so the perf
check's screen sweep exercises every field).
"""
import json
import re
import unittest

from _util import ROOT

MAIN = ROOT / "firmware" / "src" / "main.cpp"
FIXTURES = ROOT / "tools" / "fixtures" / "payloads.json"

# Keys the firmware reads that a fixture intentionally omits.
NOT_IN_FIXTURES = {
    "wifi": {"ssid", "pass"},   # provisioning; never put credentials in a fixture
}


def firmware_contract() -> dict[str, set[str]]:
    s = MAIN.read_text(encoding="utf-8")
    start = s.index("static bool process_payload(")
    body = s[start:s.index("\n}\n", start)]
    # Split at each `strcmp(src, "x") == 0` branch; the trailing else is "claude".
    parts = re.split(r'strcmp\(src,\s*"(\w+)"\)\s*==\s*0', body)
    contract: dict[str, set[str]] = {}
    for name, chunk in zip(parts[1::2], parts[2::2]):
        if "} else {" in chunk:          # last branch also holds the default
            mine, default = chunk.split("} else {", 1)
            contract[name] = set(re.findall(r'doc\["(\w+)"\]', mine))
            contract["claude"] = set(re.findall(r'doc\["(\w+)"\]', default))
        else:
            contract[name] = set(re.findall(r'doc\["(\w+)"\]', chunk))
    return contract


class PayloadContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = firmware_contract()
        cls.fixtures = {k: v for k, v in json.loads(FIXTURES.read_text()).items()
                        if not k.startswith("_")}

    def test_parser_found_every_src(self):
        for src in ("claude", "copilot", "sysinfo", "vscode", "act", "ci", "sum",
                    "env", "aurora", "status", "wifi"):
            self.assertIn(src, self.contract, f"process_payload() has no '{src}' branch?")

    def test_fixture_keys_are_read_by_firmware(self):
        for src, payload in self.fixtures.items():
            with self.subTest(src=src):
                self.assertIn(src, self.contract)
                extra = set(payload) - {"src"} - self.contract[src]
                self.assertFalse(extra, f"fixture '{src}' sends keys the firmware ignores: {extra}")

    def test_every_firmware_key_has_fixture_coverage(self):
        for src, keys in self.contract.items():
            with self.subTest(src=src):
                want = keys - NOT_IN_FIXTURES.get(src, set())
                if not want:
                    continue
                self.assertIn(src, self.fixtures, f"no fixture for src '{src}'")
                missing = want - set(self.fixtures[src])
                self.assertFalse(missing, f"fixture '{src}' doesn't cover firmware keys {missing}")


if __name__ == "__main__":
    unittest.main()
