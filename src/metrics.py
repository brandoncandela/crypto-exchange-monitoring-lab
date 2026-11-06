"""Score synthetic customer–typology labels, never real-world illicit activity.

An alert inherits the customer's label for that rule. This is a label-based
precision proxy, not an independently adjudicated event outcome. No exhaustive
event labels exist, so alert recall is deliberately unavailable.
"""
from __future__ import annotations


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score(customers: list[dict], alerts: list[dict], targets: dict, titles: dict) -> list[dict]:
    labels = {c["customer_id"]: set(c["seeded_typologies"]) for c in customers}
    results = []
    for rule_id, target in targets.items():
        rows = [a for a in alerts if a["rule_id"] == rule_id]
        hit = {a["customer_id"] for a in rows}
        seeded = {cid for cid, values in labels.items() if target in values}
        tp, fp, fn = len(hit & seeded), len(hit - seeded), len(seeded - hit)
        true_alerts = sum(target in labels[a["customer_id"]] for a in rows)
        results.append({
            "rule_id": rule_id, "title": titles[rule_id], "target": target,
            "customer_level": {
                "true_positives": tp, "false_positives": fp, "false_negatives": fn,
                "customers_alerted": len(hit), "seeded_customers": len(seeded),
                "precision": ratio(tp, len(hit)), "recall": ratio(tp, len(seeded)),
            },
            "alert_level": {
                "alerts": len(rows), "label_positive_alerts": true_alerts,
                "label_negative_alerts": len(rows) - true_alerts,
                "precision": ratio(true_alerts, len(rows)), "recall": None,
                "recall_denominator": None,
                "recall_unavailable_reason": "No exhaustive event-level reference set; customer labels cannot count all missed events.",
                "label_basis": "Customer–typology label inherited by each alert; not event adjudication.",
            },
            "true_positive_customers": sorted(hit & seeded),
            "false_positive_customers": sorted(hit - seeded),
            "missed_customers": sorted(seeded - hit),
        })
    return results
