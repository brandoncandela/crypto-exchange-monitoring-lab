"""Build the monitoring lab: a fictional exchange ledger over real public data.

Customers and their ledger are synthetic and deterministic. Counterparty
addresses are either synthetic or real public addresses taken from the
snapshot: OFAC-listed addresses and wallets that transacted with them on Tron.
The SQL rules in sql/rules run against the result and the dashboard export is
written to dist/data/lab.json.
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshot"
OUT = ROOT / "dist" / "data"
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = 30
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Which seeded typology each rule is meant to find; used to score the rules.
RULE_TARGETS = {
    "R01": "sanctions_direct",
    "R02": "sanctions_one_hop",
    "R03": "pass_through",
    "R04": "structuring",
    "R05": "fan_out",
    "R06": "travel_rule_gap",
}
RULE_TITLES = {
    "R01": "Direct sanctions exposure",
    "R02": "Indirect sanctions exposure (one hop)",
    "R03": "Pass-through (rapid in and out)",
    "R04": "Structuring below the Travel Rule threshold",
    "R05": "Fan-out to new addresses",
    "R06": "Travel Rule information gap",
}
# Plain-English explanation of each rule and the first checks an analyst would make, shown in the dashboard.
RULE_PLAIN = {
    "R01": "The customer sent crypto to, or received it from, a wallet on the U.S. sanctions list.",
    "R02": "The other wallet isn't on the sanctions list, but it has sent or received USDT directly with one that is.",
    "R03": "Money came in and most of it went back out within an hour, so the account may just be a stop along the way.",
    "R04": "Several withdrawals in one day, each just under $3,000, where sender and recipient details become required.",
    "R05": "One deposit was split and sent to five or more wallets the customer had never paid before.",
    "R06": "A withdrawal of $3,000 or more went out without the recipient details the Travel Rule requires.",
}
RULE_NEXT = {
    "R01": ["Freeze or hold per policy and escalate to the sanctions team right away.",
            "Confirm the address matches the OFAC entry character for character.",
            "Check whether other customers have touched the same address."],
    "R02": ["Look at who the other wallet is: a big exchange touching many sanctioned wallets means something different "
            "from a private wallet dealing with just one.",
            "Open the on-chain link and check the date and amount against the customer's activity.",
            "Ask the customer what the transfer was for if the explanation isn't obvious."],
    "R03": ["Compare against the customer's profile: is fast in-and-out normal for this kind of customer?",
            "Check where the money went next and whether those wallets show up elsewhere.",
            "Ask for the source of funds if the deposit is large for this customer."],
    "R04": ["Line up the withdrawals by time and amount. Do they look split on purpose?",
            "Check whether the destination wallets belong to the same person.",
            "Collect Travel Rule details for the whole amount and consider a report if splitting is deliberate."],
    "R05": ["Check whether the customer has a business reason to pay many wallets, like payroll or payouts.",
            "See if the new wallets send money back on to a single place.",
            "Compare the dispersed total to what the customer normally moves."],
    "R06": ["Request the missing recipient details before processing more withdrawals.",
            "Check whether this is a one-off or a pattern for the customer.",
            "Treat it as a process fix unless other alerts point to something more."],
}


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Exchange:
    """Accumulates customers and ledger rows with deterministic ids and addresses."""

    def __init__(self, prices: dict, rng: random.Random) -> None:
        self.prices = {"USDT-TRC20": prices["tether"]["usd"], "ETH": prices["ethereum"]["usd"]}
        self.rng = rng
        self.customers: list[dict] = []
        self.transfers: list[dict] = []

    def tron_address(self) -> str:
        return "T" + "".join(self.rng.choice(BASE58) for _ in range(33))

    def eth_address(self) -> str:
        return "0x" + "".join(self.rng.choice("0123456789abcdef") for _ in range(40))

    def beneficiary(self) -> str:
        return f"Beneficiary B-{self.rng.randint(1000, 9999)} (fictional)"

    def customer(self, segment: str, kyc_risk: str, expected: float, scenario: str,
                 typology: str | None = None) -> str:
        customer_id = f"C-{len(self.customers) + 1:03d}"
        onboarded = START - timedelta(days=self.rng.randint(60, 900))
        self.customers.append({
            "customer_id": customer_id, "segment": segment, "kyc_risk": kyc_risk,
            "expected_monthly_usd": expected, "onboarded_at": stamp(onboarded),
            "scenario": scenario, "seeded_typology": typology,
        })
        return customer_id

    def move(self, customer_id: str, direction: str, usd: float, when: datetime, counterparty: str,
             source: str = "synthetic", asset: str = "USDT-TRC20", beneficiary: str | None = "auto") -> str:
        """Record a transfer. Withdrawals get beneficiary details unless told otherwise."""
        amount = round(usd / self.prices[asset], 6 if asset == "ETH" else 2)
        if direction == "deposit":
            beneficiary = None
        elif beneficiary == "auto":
            beneficiary = self.beneficiary()
        tx_id = f"TX-{len(self.transfers) + 1:05d}"
        self.transfers.append({
            "tx_id": tx_id, "customer_id": customer_id, "direction": direction, "asset": asset,
            "amount": amount, "usd_value": round(amount * self.prices[asset], 2),
            "counterparty_address": counterparty, "counterparty_source": source,
            "beneficiary_name": beneficiary, "occurred_at": stamp(when),
        })
        return tx_id


def one_hop_profiles(chain: list[dict], sanctioned: set[str]) -> dict[str, dict]:
    """Per counterparty of a sanctioned Tron address: distinct sanctioned touched and USDT moved."""
    profile: dict[str, dict] = defaultdict(lambda: {"sanctioned": set(), "usdt": 0.0})
    for tx in chain:
        other = tx["to_address"] if tx["from_address"] == tx["sanctioned_address"] else tx["from_address"]
        if other in sanctioned:
            continue
        profile[other]["sanctioned"].add(tx["sanctioned_address"])
        profile[other]["usdt"] += tx["amount_usdt"]
    return profile


def populate(ex: Exchange, ofac: list[dict], chain: list[dict]) -> None:
    rng = ex.rng
    sanctioned = {a["address"] for a in ofac}
    tron_listed = sorted({tx["sanctioned_address"] for tx in chain})
    eth_listed = sorted({a["address"] for a in ofac if a["asset"] == "ETH"})
    hops = one_hop_profiles(chain, sanctioned)
    # A wallet that dealt with exactly one sanctioned address in meaningful size: a strong lead.
    focused = sorted((a for a, p in hops.items() if len(p["sanctioned"]) == 1 and 20_000 <= p["usdt"] <= 500_000),
                     key=lambda a: (-hops[a]["usdt"], a))
    # The wallet touching the most sanctioned addresses. That pattern is typical of a large service, though
    # nothing here verifies who controls it; it stands in for the "customer's account elsewhere" story.
    service = max(hops, key=lambda a: (len(hops[a]["sanctioned"]), hops[a]["usdt"], a))
    day = lambda d, h=0, m=0: START + timedelta(days=d, hours=h, minutes=m)

    # Direct sanctions exposure.
    c = ex.customer("retail", "medium", 6000, "Withdraws USDT to an OFAC-listed Tron address.", "sanctions_direct")
    ex.move(c, "deposit", 5200, day(3, 9), ex.tron_address())
    ex.move(c, "withdrawal", 4800, day(6, 14, 12), tron_listed[0], "ofac")
    c = ex.customer("high_net_worth", "medium", 40000, "Receives an ETH deposit from an OFAC-listed address.",
                    "sanctions_direct")
    ex.move(c, "deposit", 4100, day(11, 18, 40), eth_listed[0], "ofac", asset="ETH")
    ex.move(c, "withdrawal", 3900, day(15, 10), ex.eth_address(), asset="ETH")

    # Indirect exposure through wallets that dealt with a sanctioned address.
    c = ex.customer("retail", "low", 8000, "Deposit arrives from a wallet that transacted with a sanctioned address.",
                    "sanctions_one_hop")
    ex.move(c, "deposit", 12500, day(8, 22, 5), focused[0], "tron_one_hop")
    ex.move(c, "withdrawal", 11800, day(10, 9, 30), ex.tron_address())
    c = ex.customer("merchant", "medium", 25000, "Pays out to a wallet that transacted with a sanctioned address.",
                    "sanctions_one_hop")
    ex.move(c, "deposit", 18000, day(4, 12), ex.tron_address())
    ex.move(c, "withdrawal", 9500, day(5, 16, 45), focused[1], "tron_one_hop")
    ex.move(c, "withdrawal", 6200, day(19, 11, 5), focused[1], "tron_one_hop")
    c = ex.customer("retail", "low", 5000, "Lookalike: the fictional customer says the destination is their account at "
                    "another exchange. The wallet is real and touched many sanctioned addresses, typical of a large "
                    "service, but who controls it is not verified here.")
    ex.move(c, "deposit", 3000, day(2, 13), ex.tron_address())
    ex.move(c, "withdrawal", 2100, day(9, 20, 15), service, "tron_one_hop")

    # Pass-through: in and out within the hour.
    for usd, gap in ((25000, 22), (61000, 41)):
        c = ex.customer("retail", "medium", 7000, f"${usd:,} deposit mostly withdrawn within {gap + 9} minutes.",
                        "pass_through")
        when = day(rng.randint(5, 25), rng.randint(0, 23), rng.randint(0, 59))
        ex.move(c, "deposit", usd, when, ex.tron_address())
        ex.move(c, "withdrawal", round(usd * 0.55, 2), when + timedelta(minutes=gap), ex.tron_address())
        ex.move(c, "withdrawal", round(usd * 0.41, 2), when + timedelta(minutes=gap + 9), ex.tron_address())
    c = ex.customer("otc_desk", "medium", 900000, "Lookalike: licensed OTC desk that settles client trades within "
                    "minutes, as documented at onboarding.")
    desk_wallets = [ex.tron_address() for _ in range(3)]
    for d in range(1, DAYS, 3):
        when = day(d, 15, rng.randint(0, 50))
        usd = rng.randint(40, 120) * 1000
        ex.move(c, "deposit", usd, when, ex.tron_address())
        ex.move(c, "withdrawal", usd * 0.995, when + timedelta(minutes=rng.randint(8, 30)), rng.choice(desk_wallets))

    # Structuring just under the $3,000 Travel Rule threshold.
    for start_day in (12, 21):
        c = ex.customer("retail", "low", 4000, "Five withdrawals between $2,700 and $2,990 in one day.", "structuring")
        ex.move(c, "deposit", 15000, day(start_day - 1, 10), ex.tron_address())
        targets = [ex.tron_address() for _ in range(2)]
        for i in range(5):
            ex.move(c, "withdrawal", rng.randint(2700, 2990), day(start_day, 8 + i * 2, rng.randint(0, 59)),
                    targets[i % 2])

    # Fan-out: one deposit dispersed to many fresh wallets.
    for usd, legs, low, high in ((40000, 8, 3500, 5200), (18000, 7, 1500, 2400)):
        c = ex.customer("retail", "medium", 6000, f"${usd:,} deposit dispersed to {legs} new wallets within 12 hours.",
                        "fan_out")
        when = day(rng.randint(6, 24), rng.randint(0, 10))
        ex.move(c, "deposit", usd, when, ex.tron_address())
        for i in range(legs):
            ex.move(c, "withdrawal", rng.randint(low, high), when + timedelta(hours=2 + i * 1.3), ex.tron_address())
    c = ex.customer("payroll_business", "low", 60000, "Lookalike: pays ten contractors $2,600 to $2,950 twice a "
                    "month; the first run of the month goes to wallets it has not paid before.")
    contractors = [ex.tron_address() for _ in range(10)]
    for run_day in (1, 15):
        ex.move(c, "deposit", 30000, day(run_day, 7), ex.tron_address())
        for i, wallet in enumerate(contractors):
            ex.move(c, "withdrawal", rng.randint(2600, 2950), day(run_day, 9, i * 12), wallet)

    # Travel Rule gaps: large withdrawals without beneficiary information.
    for usd in (5200, 12400):
        c = ex.customer("high_net_worth", "low", 30000, f"${usd:,} withdrawal with no beneficiary information.",
                        "travel_rule_gap")
        ex.move(c, "deposit", usd + 4000, day(rng.randint(2, 10), 11), ex.tron_address())
        ex.move(c, "withdrawal", usd, day(rng.randint(12, 26), 16), ex.tron_address(), beneficiary=None)

    # Ordinary customers: periodic deposits, withdrawals hours or days later to a few recurring wallets.
    segments = [("retail", "low", 3000)] * 9 + [("high_net_worth", "low", 50000)] * 3 + [("merchant", "low", 20000)] * 3
    for segment, risk, expected in segments:
        c = ex.customer(segment, risk, expected, "Ordinary activity consistent with the customer profile.")
        wallets = [ex.tron_address() for _ in range(rng.randint(1, 2))]
        for _ in range(rng.randint(3, 8)):
            when = day(rng.randint(0, DAYS - 3), rng.randint(0, 23), rng.randint(0, 59))
            usd = round(rng.uniform(0.05, 0.4) * expected, 2)
            ex.move(c, "deposit", usd, when, ex.tron_address())
            if rng.random() < 0.7:
                ex.move(c, "withdrawal", round(usd * rng.uniform(0.3, 0.9), 2),
                        when + timedelta(hours=rng.randint(4, 60)), rng.choice(wallets))


def build() -> dict:
    snapshot = {name: json.loads((SNAPSHOT / f"{name}.json").read_text())
                for name in ("manifest", "ofac_crypto_addresses", "tron_usdt_transfers", "prices")}
    ex = Exchange(snapshot["prices"], random.Random(20261105))
    populate(ex, snapshot["ofac_crypto_addresses"], snapshot["tron_usdt_transfers"])

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript((ROOT / "sql" / "schema.sql").read_text())
    con.executemany("INSERT INTO customers VALUES (:customer_id, :segment, :kyc_risk, :expected_monthly_usd, "
                    ":onboarded_at, :scenario, :seeded_typology)", ex.customers)
    con.executemany("INSERT INTO transfers VALUES (:tx_id, :customer_id, :direction, :asset, :amount, :usd_value, "
                    ":counterparty_address, :counterparty_source, :beneficiary_name, :occurred_at)", ex.transfers)
    con.executemany("INSERT OR IGNORE INTO sanctioned_addresses VALUES (:address, :asset, :sdn_id, :name, :program)",
                    snapshot["ofac_crypto_addresses"])
    con.executemany("INSERT OR IGNORE INTO chain_transfers VALUES (:tx_hash, :sanctioned_address, :from_address, "
                    ":to_address, :amount_usdt, :block_time)", snapshot["tron_usdt_transfers"])

    alerts, rules = [], []
    for path in sorted((ROOT / "sql" / "rules").glob("R*.sql")):
        rule_id, sql = path.name[:3], path.read_text()
        rules.append({"rule_id": rule_id, "title": RULE_TITLES[rule_id], "plain": RULE_PLAIN[rule_id],
                      "next_steps": RULE_NEXT[rule_id], "file": f"sql/rules/{path.name}", "sql": sql})
        for row in con.execute(sql):
            alert = dict(row)
            alert["evidence"] = json.loads(alert["evidence"])
            alerts.append(alert)
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(key=lambda a: (severity_rank[a["severity"]], a["rule_id"], a["customer_id"], a["anchor_tx_id"]))
    for i, alert in enumerate(alerts, 1):
        alert["alert_id"] = f"A-{i:03d}"

    typology = {c["customer_id"]: c["seeded_typology"] for c in ex.customers}
    metrics = []
    for rule_id, target in RULE_TARGETS.items():
        hit = {a["customer_id"] for a in alerts if a["rule_id"] == rule_id}
        seeded = {cid for cid, t in typology.items() if t == target}
        true_hits = hit & seeded
        metrics.append({
            "rule_id": rule_id, "title": RULE_TITLES[rule_id], "target": target,
            "alerts": sum(a["rule_id"] == rule_id for a in alerts),
            "customers_alerted": len(hit), "seeded_customers": len(seeded),
            "precision": round(len(true_hits) / len(hit), 3) if hit else None,
            "recall": round(len(true_hits) / len(seeded), 3) if seeded else None,
            "false_positive_customers": sorted(hit - seeded),
            "missed_customers": sorted(seeded - hit),
        })

    return {
        "snapshot": snapshot["manifest"],
        "prices": snapshot["prices"],
        "counts": {
            "customers": len(ex.customers),
            "transfers": len(ex.transfers),
            "sanctioned_addresses": con.execute("SELECT COUNT(DISTINCT address) FROM sanctioned_addresses").fetchone()[0],
            "chain_transfers": con.execute("SELECT COUNT(*) FROM chain_transfers").fetchone()[0],
            "alerts": len(alerts),
        },
        "customers": ex.customers,
        "transfers": ex.transfers,
        "alerts": alerts,
        "rules": rules,
        "metrics": metrics,
    }


def main() -> None:
    lab = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lab.json").write_text(json.dumps(lab, separators=(",", ":")) + "\n")
    print(f"{lab['counts']['customers']} customers, {lab['counts']['transfers']} transfers, "
          f"{lab['counts']['alerts']} alerts")
    for m in lab["metrics"]:
        print(f"  {m['rule_id']} {m['title']}: {m['alerts']} alerts, precision {m['precision']}, recall {m['recall']}"
              + (f", false positives {m['false_positive_customers']}" if m["false_positive_customers"] else ""))


if __name__ == "__main__":
    main()
