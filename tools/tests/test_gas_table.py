"""GAS_DEFS[] in firmware/src/gas_sensor.cpp vs the MQ-135 reference curves.

The coefficients are the MQSensorsLib fits to the datasheet's Fig. 3
(ppm = a * (Rs/R0_ds)^b, clean air Rs/R0_ds = 3.6). A typo there compiles
fine and just prints a plausible-looking wrong number, so pin them here and
check the excess-over-clean-air math the firmware applies.
"""
import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "firmware" / "src"

REFERENCE = {  # key: (a, b) -- MQSensorsLib examples/MQ-135
    "co2": (110.47, -2.862),
    "nh3": (102.2, -2.473),
    "alcohol": (77.255, -3.18),
    "toluene": (44.947, -3.445),
    "acetone": (34.668, -3.369),
    "co": (605.18, -3.937),
}
ORDER = ["co2", "nh3", "alcohol", "toluene", "acetone", "co"]  # AirGas enum in data.h
DS_CLEAN = 3.6


def parse_table():
    s = (SRC / "gas_sensor.cpp").read_text(encoding="utf-8")
    body = re.search(r"GAS_DEFS\[AIR_GAS_COUNT\]\s*=\s*\{(.*?)\n\};", s, re.S).group(1)
    rows = []
    for m in re.finditer(r'\{\s*"(\w+)",\s*"([^"]+)",([^}]*)\}', body):
        nums = [float(x.strip().rstrip("f")) for x in m.group(3).split(",") if x.strip()]
        a, b, base, lo, hi, caution, alarm = nums
        rows.append(dict(key=m.group(1), name=m.group(2), a=a, b=b, base=base,
                         lo=lo, hi=hi, caution=caution, alarm=alarm))
    return rows


def ppm(row, ratio):  # mirrors gas_ppm() in gas_sensor.cpp
    excess = row["a"] * ((DS_CLEAN * ratio) ** row["b"] - DS_CLEAN ** row["b"])
    return row["base"] + max(excess, 0.0)


class GasTable(unittest.TestCase):
    def setUp(self):
        self.rows = parse_table()
        self.by_key = {r["key"]: r for r in self.rows}

    def test_order_matches_airgas_enum(self):
        self.assertEqual([r["key"] for r in self.rows], ORDER)
        enum = re.search(r"enum AirGas \{([^}]*)\}", (SRC / "data.h").read_text(encoding="utf-8")).group(1)
        self.assertEqual([x.strip() for x in enum.split(",")][-1], "AIR_GAS_COUNT")
        self.assertEqual(len([x for x in enum.split(",") if x.strip()]) - 1, len(ORDER))

    def test_coefficients_match_reference(self):
        for key, (a, b) in REFERENCE.items():
            self.assertAlmostEqual(self.by_key[key]["a"], a, places=3, msg=key)
            self.assertAlmostEqual(self.by_key[key]["b"], b, places=3, msg=key)

    def test_clean_air_reads_ambient(self):
        for r in self.rows:
            self.assertAlmostEqual(ppm(r, 1.0), r["base"], places=6, msg=r["key"])
            self.assertEqual(ppm(r, 1.2), r["base"], msg=r["key"])  # cleaner than baseline: clamp

    def test_known_points(self):
        # Halving Rs: NH3 ~20 ppm equivalent, CO2 barely moves (sensor is nearly CO2-blind).
        self.assertAlmostEqual(ppm(self.by_key["nh3"], 0.5), 19.6, delta=0.5)
        self.assertLess(ppm(self.by_key["co2"], 0.5), 425)
        self.assertGreater(ppm(self.by_key["co2"], 0.5), 410)

    def test_thresholds_ordered(self):
        for r in self.rows:
            self.assertLess(r["caution"], r["alarm"], r["key"])
            self.assertLess(r["lo"], r["hi"], r["key"])


if __name__ == "__main__":
    unittest.main()
