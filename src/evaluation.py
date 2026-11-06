"""Separate deterministic challenge fixtures. No detector reads these labels.

Authored after the baseline; useful for regression/challenge testing, not a
blind holdout or a representative production sample. Controls are fixed before
this set is run. Multiple review-worthy typologies may coexist per customer.
"""
from datetime import timedelta


def populate(ex, ofac, chain, start):
    day = lambda n=0: start + timedelta(days=n, hours=10)
    tron = sorted({t["sanctioned_address"] for t in chain})[0]
    listed = {a["address"] for a in ofac}
    hop = next(a for t in chain for a in (t["from_address"], t["to_address"])
               if a not in listed)

    def client(description, *labels, segment="retail"):
        cid = ex.customer(segment, "medium", 20000, description)
        ex.customers[-1]["seeded_typologies"] = list(labels)
        return cid

    def rapid(description, amount, share, seconds, labels=("pass_through",), segment="retail"):
        c = client(description, *labels, segment=segment)
        ex.move(c, "deposit", amount, day(), ex.tron_address())
        ex.move(c, "withdrawal", amount * share, day() + timedelta(seconds=seconds), ex.tron_address())

    # Exact boundaries and intentional misses; risk labels express authored
    # review priority, not whether the current rule's numeric condition passes.
    rapid("Boundary: $1,000 deposit, 80% out at exactly 60 minutes; review-worthy.", 1000, .8, 3600)
    rapid("Miss: 96% out after 60 minutes and one second; review-worthy.", 10000, .96, 3601)
    rapid("Miss: 79.99% out in 20 minutes; review-worthy context.", 10000, .7999, 1200)
    rapid("Miss: $999.99 deposit fully withdrawn in 10 minutes; review-worthy context.", 999.99, 1, 600)
    rapid("Lookalike: documented merchant settlement, same-hour payout.", 10000, .95, 1800, labels=(), segment="merchant")
    rapid("Lookalike: documented high-value OTC settlement, not an automatic exemption.", 75000, .99, 1200,
          labels=(), segment="otc_desk")
    # Demonstrates why an OTC segment exemption would silently remove risk.
    rapid("Review-worthy OTC activity with unexplained source of funds.", 75000, .98, 1200, segment="otc_desk")

    c = client("Overlapping direct sanctions, pass-through and missing recipient details.",
               "sanctions_direct", "pass_through", "travel_rule_gap")
    ex.move(c, "deposit", 12000, day(), ex.tron_address())
    ex.move(c, "withdrawal", 11000, day() + timedelta(minutes=20), tron, "ofac", beneficiary=None)
    c = client("Overlapping one-hop exposure and missing recipient details.", "sanctions_one_hop", "travel_rule_gap")
    ex.move(c, "withdrawal", 5000, day(), hop, "tron_one_hop", beneficiary="  ")

    c = client("Overlapping structuring and fan-out: five fresh wallets, $2,600 each.", "structuring", "fan_out")
    ex.move(c, "deposit", 15000, day(), ex.tron_address())
    for i in range(5):
        ex.move(c, "withdrawal", 2600, day() + timedelta(hours=2+i), ex.tron_address())
    c = client("Miss: only three near-threshold withdrawals, but review-worthy context.", "structuring")
    for i in range(3):
        ex.move(c, "withdrawal", 2999, day() + timedelta(hours=i), ex.tron_address())
    c = client("Miss: four new destinations rather than five; review-worthy dispersal.", "fan_out")
    ex.move(c, "deposit", 20000, day(), ex.tron_address())
    for i in range(4):
        ex.move(c, "withdrawal", 3000, day() + timedelta(hours=2+i), ex.tron_address())

    c = client("Lookalike: new contractor payroll; benign for structuring and fan-out.", segment="payroll_business")
    ex.move(c, "deposit", 15000, day(), ex.tron_address())
    for i in range(5):
        ex.move(c, "withdrawal", 2600, day() + timedelta(hours=2+i), ex.tron_address())
    c = client("Boundary: $3,000 withdrawal without beneficiary details.", "travel_rule_gap")
    ex.move(c, "withdrawal", 3000, day(), ex.tron_address(), beneficiary=None)
    c = client("Boundary: $2,999.99 with missing details is below this control's scope.")
    ex.move(c, "withdrawal", 2999.99, day(), ex.tron_address(), beneficiary=None)
    c = client("Boundary: direct listed-address exposure at $1.", "sanctions_direct")
    ex.move(c, "withdrawal", 1, day(), tron, "ofac")
    c = client("Boundary: ordinary $3,000 withdrawal with recipient details.")
    ex.move(c, "withdrawal", 3000, day(), ex.tron_address())
