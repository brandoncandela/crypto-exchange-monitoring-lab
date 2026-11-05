-- Fictional exchange customers. seeded_typology is the answer key used only to
-- measure the rules; it is NULL for customers with no seeded typology.
CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  segment TEXT NOT NULL,              -- retail, high_net_worth, otc_desk, payroll_business, merchant
  kyc_risk TEXT NOT NULL CHECK (kyc_risk IN ('low', 'medium', 'high')),
  expected_monthly_usd REAL NOT NULL,
  onboarded_at TEXT NOT NULL,
  scenario TEXT NOT NULL,             -- plain-language description of the seeded behavior
  seeded_typology TEXT
);

-- The exchange's ledger: customer deposits and withdrawals. Times are UTC
-- 'YYYY-MM-DD HH:MM:SS' so SQLite datetime() arithmetic works directly.
CREATE TABLE transfers (
  tx_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers (customer_id),
  direction TEXT NOT NULL CHECK (direction IN ('deposit', 'withdrawal')),
  asset TEXT NOT NULL,                -- USDT-TRC20 or ETH
  amount REAL NOT NULL CHECK (amount > 0),
  usd_value REAL NOT NULL,
  counterparty_address TEXT NOT NULL,
  counterparty_source TEXT NOT NULL CHECK (counterparty_source IN ('synthetic', 'ofac', 'tron_one_hop')),
  beneficiary_name TEXT,              -- Travel Rule information collected for withdrawals; NULL if missing
  occurred_at TEXT NOT NULL
);
CREATE INDEX transfers_customer_time ON transfers (customer_id, occurred_at);
CREATE INDEX transfers_counterparty ON transfers (counterparty_address);

-- Digital currency addresses from the OFAC SDN list (real, public).
CREATE TABLE sanctioned_addresses (
  address TEXT NOT NULL,
  asset TEXT NOT NULL,
  sdn_id INTEGER NOT NULL,
  sdn_name TEXT NOT NULL,
  program TEXT NOT NULL,
  PRIMARY KEY (address, sdn_id)
);

-- Real on-chain USDT transfers in and out of sanctioned Tron addresses.
CREATE TABLE chain_transfers (
  tx_hash TEXT NOT NULL,
  sanctioned_address TEXT NOT NULL,
  from_address TEXT NOT NULL,
  to_address TEXT NOT NULL,
  amount_usdt REAL NOT NULL,
  block_time TEXT NOT NULL,
  PRIMARY KEY (tx_hash, sanctioned_address)
);
CREATE INDEX chain_from ON chain_transfers (from_address);
CREATE INDEX chain_to ON chain_transfers (to_address);
