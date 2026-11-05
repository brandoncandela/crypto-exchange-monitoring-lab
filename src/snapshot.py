"""Download the public data the lab is built on and save it under data/snapshot/.

Run this only to refresh the snapshot. build_lab.py reads the saved files, so the
lab rebuilds identically offline and reviewers see the same alerts.

Sources (no API keys):
- OFAC SDN list: digital currency addresses listed in entry remarks
- TronGrid: recent USDT (TRC-20) transfers of each sanctioned Tron address
- CoinGecko: spot prices used to value transfers in USD
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "snapshot"
OFAC_SDN = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
TRONGRID = "https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=50&contract_address={contract}"
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=tether,ethereum,tron&vs_currencies=usd"
ADDRESS = re.compile(r"Digital Currency Address - (\w+) ([A-Za-z0-9]+)")
HEADERS = {"User-Agent": "crypto-exchange-monitoring-lab/0.1 (portfolio project)"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def sanctioned_addresses() -> list[dict]:
    """Every digital currency address in the SDN list, with the entry it belongs to."""
    text = fetch(OFAC_SDN).decode("latin-1")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 12 or not row[0].isdigit():
            continue
        for asset, address in ADDRESS.findall(row[11]):
            rows.append({"sdn_id": int(row[0]), "name": row[1], "program": row[3],
                         "asset": asset, "address": address})
    return rows


def tron_history(addresses: list[str]) -> list[dict]:
    """Recent USDT transfers in and out of each sanctioned Tron address."""
    transfers = []
    for address in addresses:
        payload = json.loads(fetch(TRONGRID.format(address=address, contract=USDT_TRC20)))
        for tx in payload.get("data", []):
            transfers.append({
                "sanctioned_address": address,
                "tx_hash": tx["transaction_id"],
                "block_time": datetime.fromtimestamp(tx["block_timestamp"] / 1000, timezone.utc).isoformat(),
                "from_address": tx["from"],
                "to_address": tx["to"],
                "amount_usdt": int(tx["value"]) / 10 ** int(tx["token_info"]["decimals"]),
            })
        time.sleep(0.5)  # stay well under TronGrid's keyless rate limit
    return transfers


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    addresses = sanctioned_addresses()
    tron = sorted({a["address"] for a in addresses if a["address"].startswith("T") and len(a["address"]) == 34})
    transfers = tron_history(tron)
    prices = json.loads(fetch(COINGECKO))

    (OUT / "ofac_crypto_addresses.json").write_text(json.dumps(addresses, indent=1) + "\n")
    (OUT / "tron_usdt_transfers.json").write_text(json.dumps(transfers, indent=1) + "\n")
    (OUT / "prices.json").write_text(json.dumps(prices, indent=1) + "\n")
    (OUT / "manifest.json").write_text(json.dumps({
        "retrieved_at": retrieved_at,
        "sources": {"ofac": OFAC_SDN, "tron": TRONGRID.split("/v1")[0], "prices": COINGECKO},
        "counts": {"sanctioned_addresses": len(addresses), "tron_addresses_queried": len(tron),
                   "tron_transfers": len(transfers)},
    }, indent=1) + "\n")
    print(f"{len(addresses)} sanctioned addresses, {len(tron)} Tron addresses queried, {len(transfers)} USDT transfers")


if __name__ == "__main__":
    main()
