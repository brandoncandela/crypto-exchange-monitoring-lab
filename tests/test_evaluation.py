"""Independent arithmetic, baseline preservation and challenge-set checks."""
import copy
import csv
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_lab
from metrics import score


class Metrics(unittest.TestCase):
    def test_repeats_and_multilabel_customers_have_different_denominators(self):
        customers = [{"customer_id": "positive", "seeded_typologies": ["a", "b"]},
                     {"customer_id": "benign", "seeded_typologies": []},
                     {"customer_id": "missed", "seeded_typologies": ["a"]}]
        alerts = [{"rule_id": "A", "customer_id": "positive"}] + [
            {"rule_id": "A", "customer_id": "benign"} for _ in range(10)]
        m = score(customers, alerts, {"A": "a", "B": "b"}, {"A": "A", "B": "B"})
        self.assertEqual(m[0]["customer_level"]["precision"], 1 / 2)
        self.assertEqual(m[0]["customer_level"]["recall"], 1 / 2)
        self.assertEqual(m[0]["alert_level"]["precision"], 1 / 11)
        self.assertEqual(m[1]["customer_level"]["seeded_customers"], 1)
        self.assertEqual(m[1]["missed_customers"], ["positive"])
        self.assertIsNone(m[0]["alert_level"]["recall"])
        self.assertIsNone(m[0]["alert_level"]["recall_denominator"])

    def test_zero_denominators_are_unknown(self):
        m = score([], [], {"A": "a"}, {"A": "A"})[0]
        self.assertIsNone(m["customer_level"]["precision"])
        self.assertIsNone(m["customer_level"]["recall"])
        self.assertIsNone(m["alert_level"]["precision"])


class Evaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {(d, c): build_lab.build(d, c) for d in ("baseline", "evaluation")
                    for c in ("baseline", "proposed")}

    def test_original_fixtures_and_alerts_preserved(self):
        lab = copy.deepcopy(self.runs["baseline", "baseline"])
        for c in lab["customers"]:
            del c["seeded_typologies"]  # additive multi-label export; legacy values unchanged
        expected = {
            "customers": "4c22375a9a8c8df6521df6ac9b246a68d50ee345db8cc6127f35c1c825515e1f",
            "transfers": "99fbbd6839048ccce0f7d522aa68e0f9d6b213373fe71437e55a8bd173a17d0e",
            "alerts": "d7a0b5c7a4dc02fd5ce65af2f39aefca0c9a0bca8d8960cfcbc0344db4681516",
        }
        for key, digest in expected.items():
            actual = hashlib.sha256(json.dumps(lab[key], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(actual, digest, key)

    def test_otc_alert_precision_is_not_customer_precision(self):
        m = self.runs["baseline", "baseline"]["metrics"][2]
        self.assertEqual(m["customer_level"]["precision"], 2 / 3)
        self.assertEqual(m["alert_level"]["precision"], 2 / 12)
        self.assertEqual(m["alert_level"]["label_negative_alerts"], 10)

    def test_evaluation_is_deterministic_with_overlap_and_misses(self):
        lab = self.runs["evaluation", "baseline"]
        self.assertEqual(lab, build_lab.build("evaluation"))
        overlap = next(c for c in lab["customers"] if c["customer_id"] == "C-008")
        self.assertEqual(set(overlap["seeded_typologies"]), {"sanctions_direct", "pass_through", "travel_rule_gap"})
        self.assertEqual({a["rule_id"] for a in lab["alerts"] if a["customer_id"] == "C-008"}, {"R01", "R03", "R06"})
        m = lab["metrics"][2]
        self.assertEqual(m["missed_customers"], ["C-002", "C-003", "C-004"])
        self.assertEqual(m["customer_level"]["recall"], 3 / 6)
        self.assertEqual(lab["metrics"][3]["missed_customers"], ["C-011"])
        self.assertEqual(lab["metrics"][4]["missed_customers"], ["C-012"])

    def test_changing_evaluation_labels_cannot_change_detection(self):
        populate = build_lab.populate_evaluation
        def without_labels(*args):
            populate(*args)
            for c in args[0].customers:
                c["seeded_typologies"] = []
                c["scenario"] = "Changed answer key"
        with patch.object(build_lab, "populate_evaluation", without_labels):
            run = build_lab.build("evaluation")
        self.assertEqual(run["alerts"], self.runs["evaluation", "baseline"]["alerts"])
        self.assertEqual(run["transfers"], self.runs["evaluation", "baseline"]["transfers"])

    def test_proposed_changes_only_r03_and_reduces_customer_recall(self):
        for dataset in ("baseline", "evaluation"):
            base, proposal = self.runs[dataset, "baseline"], self.runs[dataset, "proposed"]
            # IDs are presentation order, so compare evidence and anchors instead.
            strip = lambda a: {k: v for k, v in a.items() if k != "alert_id"}
            self.assertEqual([strip(a) for a in base["alerts"] if a["rule_id"] != "R03"],
                             [strip(a) for a in proposal["alerts"] if a["rule_id"] != "R03"])
            self.assertEqual(base["transfers"], proposal["transfers"])
            self.assertLess(proposal["metrics"][2]["customer_level"]["recall"], base["metrics"][2]["customer_level"]["recall"])

    def test_all_metrics_reconcile_with_the_generated_records(self):
        for run in self.runs.values():
            for m in run["metrics"]:
                c, a = m["customer_level"], m["alert_level"]
                positive = {x["customer_id"] for x in run["customers"] if m["target"] in x["seeded_typologies"]}
                alerts = [x for x in run["alerts"] if x["rule_id"] == m["rule_id"]]
                hit = {x["customer_id"] for x in alerts}
                self.assertEqual(c["true_positives"], len(hit & positive))
                self.assertEqual(c["false_positives"], len(hit - positive))
                self.assertEqual(c["false_negatives"], len(positive - hit))
                self.assertEqual(a["alerts"], a["label_positive_alerts"] + a["label_negative_alerts"])
                self.assertEqual(a["label_positive_alerts"], sum(x["customer_id"] in positive for x in alerts))
                self.assertIsNone(a["recall"])

    def test_committed_json_and_csv_agree_with_runs(self):
        with (ROOT / "dist/data/metrics.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 24)
        for (dataset, control), run in self.runs.items():
            name = "lab" if (dataset, control) == ("baseline", "baseline") else f"{dataset}-{control}"
            self.assertEqual(json.loads((ROOT / f"dist/data/{name}.json").read_text()), run)
            for m in run["metrics"]:
                row = next(r for r in rows if (r["dataset"], r["control"], r["rule_id"]) == (dataset, control, m["rule_id"]))
                self.assertEqual(int(row["alerts"]), m["alert_level"]["alerts"])
                self.assertEqual(float(row["customer_recall"]), m["customer_level"]["recall"])
                self.assertEqual(row["alert_recall"], "")
                self.assertEqual(row["alert_recall_denominator"], "")


if __name__ == "__main__":
    unittest.main()
