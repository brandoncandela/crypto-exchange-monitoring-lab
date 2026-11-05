"""Boundary tests for each SQL rule, using small hand-built ledgers."""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = {p.name[:3]: p.read_text() for p in (ROOT / "sql" / "rules").glob("R*.sql")}
SANCTIONED = "TSanctioned000000000000000000000"
HOP = "THopWallet0000000000000000000000"


class Ledger:
    """An empty lab database with helpers for adding just the rows a test needs."""

    def __init__(self) -> None:
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript((ROOT / "sql" / "schema.sql").read_text())
        self.con.execute("INSERT INTO customers VALUES ('C-1', 'retail', 'low', 5000, '2026-01-01 00:00:00', 'test', NULL)")
        self.n = 0

    def tx(self, direction: str, usd: float, at: str, counterparty: str = "TOther", beneficiary: str | None = "B") -> str:
        self.n += 1
        tx_id = f"T{self.n}"
        self.con.execute("INSERT INTO transfers VALUES (?, 'C-1', ?, 'USDT-TRC20', ?, ?, ?, 'synthetic', ?, ?)",
                         (tx_id, direction, usd, usd, counterparty, beneficiary if direction == "withdrawal" else None,
                          f"2026-10-01 {at}" if len(at) <= 8 else at))
        return tx_id

    def sanction(self, address: str = SANCTIONED, sdn_id: int = 1) -> None:
        self.con.execute("INSERT INTO sanctioned_addresses VALUES (?, 'USDT', ?, 'TEST ENTITY', 'TEST')", (address, sdn_id))

    def chain(self, tx_hash: str, sender: str, receiver: str, usdt: float) -> None:
        self.con.execute("INSERT INTO chain_transfers VALUES (?, ?, ?, ?, ?, '2026-06-01T00:00:00+00:00')",
                         (tx_hash, SANCTIONED, sender, receiver, usdt))

    def run(self, rule_id: str) -> list[dict]:
        rows = [dict(r) for r in self.con.execute(RULES[rule_id])]
        for row in rows:
            row["evidence"] = json.loads(row["evidence"])
        return rows


class DirectSanctions(unittest.TestCase):
    def test_any_amount_to_a_listed_address_alerts(self):
        lab = Ledger()
        lab.sanction()
        lab.tx("withdrawal", 5, "10:00", SANCTIONED)
        alerts = lab.run("R01")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_address_under_two_sdn_entries_alerts_once(self):
        lab = Ledger()
        lab.sanction(sdn_id=1)
        lab.sanction(sdn_id=2)
        lab.tx("deposit", 100, "10:00", SANCTIONED)
        self.assertEqual(len(lab.run("R01")), 1)

    def test_unlisted_counterparty_does_not_alert(self):
        lab = Ledger()
        lab.sanction()
        lab.tx("withdrawal", 50000, "10:00", "TClean")
        self.assertEqual(lab.run("R01"), [])


class OneHopSanctions(unittest.TestCase):
    def test_wallet_that_paid_a_sanctioned_address_alerts_with_largest_transfer_as_evidence(self):
        lab = Ledger()
        lab.chain("small", HOP, SANCTIONED, 2000)
        lab.chain("large", SANCTIONED, HOP, 9000)
        lab.tx("withdrawal", 700, "10:00", HOP)
        [alert] = lab.run("R02")
        self.assertEqual(alert["severity"], "high")  # 11,000 USDT with the sanctioned address
        self.assertEqual(alert["evidence"]["example_tx_hash"], "large")
        self.assertEqual(alert["evidence"]["sanctioned_touched"], 1)

    def test_small_exposure_is_medium(self):
        lab = Ledger()
        lab.chain("h1", HOP, SANCTIONED, 9999)
        lab.tx("deposit", 700, "10:00", HOP)
        self.assertEqual(lab.run("R02")[0]["severity"], "medium")

    def test_listed_counterparty_is_left_to_the_direct_rule(self):
        lab = Ledger()
        lab.sanction(HOP)
        lab.chain("h1", HOP, SANCTIONED, 50000)
        lab.tx("deposit", 700, "10:00", HOP)
        self.assertEqual(lab.run("R02"), [])


class PassThrough(unittest.TestCase):
    def test_eighty_percent_out_within_the_hour_alerts(self):
        lab = Ledger()
        lab.tx("deposit", 10000, "10:00:00")
        lab.tx("withdrawal", 5000, "10:20:00")
        lab.tx("withdrawal", 3000, "11:00:00")
        [alert] = lab.run("R03")
        self.assertEqual(alert["evidence"]["minutes_to_last_withdrawal"], 60)

    def test_just_under_eighty_percent_does_not_alert(self):
        lab = Ledger()
        lab.tx("deposit", 10000, "10:00:00")
        lab.tx("withdrawal", 7999, "10:20:00")
        self.assertEqual(lab.run("R03"), [])

    def test_withdrawal_after_sixty_minutes_does_not_count(self):
        lab = Ledger()
        lab.tx("deposit", 10000, "10:00:00")
        lab.tx("withdrawal", 9000, "11:00:01")
        self.assertEqual(lab.run("R03"), [])

    def test_small_deposits_are_ignored(self):
        lab = Ledger()
        lab.tx("deposit", 999, "10:00:00")
        lab.tx("withdrawal", 999, "10:05:00")
        self.assertEqual(lab.run("R03"), [])


class Structuring(unittest.TestCase):
    def test_four_near_threshold_withdrawals_in_a_day_alert_once(self):
        lab = Ledger()
        for hour in ("08", "11", "14", "17", "20"):
            lab.tx("withdrawal", 2600, f"{hour}:00:00")
        [alert] = lab.run("R04")  # overlapping windows collapse to one alert per customer
        self.assertEqual(alert["evidence"]["count"], 5)

    def test_withdrawals_at_the_threshold_are_outside_the_band(self):
        lab = Ledger()
        for hour in ("08", "11", "14", "17"):
            lab.tx("withdrawal", 3000, f"{hour}:00:00")
        self.assertEqual(lab.run("R04"), [])

    def test_three_withdrawals_are_not_enough(self):
        lab = Ledger()
        for hour in ("08", "11", "14"):
            lab.tx("withdrawal", 2999, f"{hour}:00:00")
        self.assertEqual(lab.run("R04"), [])

    def test_four_spread_over_more_than_a_day_do_not_alert(self):
        lab = Ledger()
        for at in ("2026-10-01 08:00:00", "2026-10-01 16:00:00", "2026-10-02 00:00:00", "2026-10-02 08:00:00"):
            lab.tx("withdrawal", 2700, at)
        self.assertEqual(lab.run("R04"), [])


class FanOut(unittest.TestCase):
    def test_five_new_wallets_after_a_deposit_alert(self):
        lab = Ledger()
        lab.tx("deposit", 10000, "08:00:00")
        for i in range(5):
            lab.tx("withdrawal", 1500, f"1{i}:00:00", f"TNew{i}")
        [alert] = lab.run("R05")
        self.assertEqual(alert["evidence"]["new_addresses"], 5)

    def test_previously_paid_wallets_are_not_new(self):
        lab = Ledger()
        lab.tx("withdrawal", 100, "2026-09-20 10:00:00", "TNew0")
        lab.tx("deposit", 10000, "08:00:00")
        for i in range(5):
            lab.tx("withdrawal", 1500, f"1{i}:00:00", f"TNew{i}")
        self.assertEqual(lab.run("R05"), [])

    def test_dispersing_less_than_half_does_not_alert(self):
        lab = Ledger()
        lab.tx("deposit", 20000, "08:00:00")
        for i in range(5):
            lab.tx("withdrawal", 1000, f"1{i}:00:00", f"TNew{i}")
        self.assertEqual(lab.run("R05"), [])


class TravelRuleGap(unittest.TestCase):
    def test_threshold_withdrawal_without_beneficiary_alerts(self):
        lab = Ledger()
        lab.tx("withdrawal", 3000, "10:00", beneficiary=None)
        lab.tx("withdrawal", 4000, "11:00", beneficiary="  ")
        self.assertEqual(len(lab.run("R06")), 2)

    def test_below_threshold_or_with_beneficiary_does_not_alert(self):
        lab = Ledger()
        lab.tx("withdrawal", 2999.99, "10:00", beneficiary=None)
        lab.tx("withdrawal", 9000, "11:00", beneficiary="Jane Doe")
        self.assertEqual(lab.run("R06"), [])


if __name__ == "__main__":
    unittest.main()
