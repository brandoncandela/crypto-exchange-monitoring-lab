"""Checks on the full build: reproducibility, scenario coverage and data provenance."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import build_lab  # noqa: E402


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = build_lab.build()

    def test_build_is_deterministic(self):
        self.assertEqual(build_lab.build(), self.lab)

    def test_every_seeded_customer_is_found_by_its_rule(self):
        for metric in self.lab["metrics"]:
            with self.subTest(rule=metric["rule_id"]):
                self.assertGreater(metric["customer_level"]["seeded_customers"], 0)
                self.assertEqual(metric["missed_customers"], [])

    def test_only_lookalikes_produce_false_positives(self):
        lookalikes = {c["customer_id"] for c in self.lab["customers"] if c["scenario"].startswith("Lookalike")}
        for metric in self.lab["metrics"]:
            with self.subTest(rule=metric["rule_id"]):
                self.assertLessEqual(set(metric["false_positive_customers"]), lookalikes)

    def test_ordinary_customers_raise_no_alerts(self):
        ordinary = {c["customer_id"] for c in self.lab["customers"] if c["scenario"].startswith("Ordinary")}
        self.assertTrue(ordinary)
        self.assertFalse({a["customer_id"] for a in self.lab["alerts"]} & ordinary)

    def test_real_addresses_are_labeled_with_their_source(self):
        snapshot = build_lab.SNAPSHOT
        listed = {a["address"] for a in build_lab.json.loads((snapshot / "ofac_crypto_addresses.json").read_text())}
        for tx in self.lab["transfers"]:
            with self.subTest(tx=tx["tx_id"]):
                self.assertEqual(tx["counterparty_address"] in listed, tx["counterparty_source"] == "ofac")

    def test_ids_are_unique(self):
        for key, rows in (("tx_id", self.lab["transfers"]), ("alert_id", self.lab["alerts"]),
                          ("customer_id", self.lab["customers"])):
            ids = [r[key] for r in rows]
            self.assertEqual(len(ids), len(set(ids)), key)


if __name__ == "__main__":
    unittest.main()
