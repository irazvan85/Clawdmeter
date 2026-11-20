"""firmware/src/gas_signal.{h,cpp}: the MQ-135 signal-stability classifier.

The module is Arduino-free on purpose, so it's compiled with the host g++
and the assert-based tests in native/test_gas_signal.cpp run here. Skipped
when g++ isn't on PATH.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _util import ROOT

SRC = ROOT / "firmware" / "src"
NATIVE = Path(__file__).resolve().parent / "native"


@unittest.skipIf(shutil.which("g++") is None, "g++ not on PATH")
class GasSignal(unittest.TestCase):
    def test_classifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "t.exe"
            build = subprocess.run(
                ["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-I", str(SRC),
                 str(NATIVE / "test_gas_signal.cpp"), str(SRC / "gas_signal.cpp"), "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
