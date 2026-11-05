-- R02 Indirect sanctions exposure (one hop)
-- The counterparty itself is not listed, but it sent USDT to, or received USDT
-- from, a sanctioned address on chain. Exposure is a lead, not a finding: large
-- services (exchanges, bridges) touch many sanctioned addresses, so the alert
-- reports how many distinct sanctioned addresses the counterparty touched and
-- how much it moved, and a reviewer decides whether the link is meaningful.
WITH params AS (
  SELECT 10000.0 AS high_exposure_usdt
),
hop AS (
  SELECT
    CASE WHEN c.from_address = c.sanctioned_address THEN c.to_address ELSE c.from_address END AS address,
    c.sanctioned_address, c.tx_hash, c.amount_usdt, c.block_time
  FROM chain_transfers AS c
),
exposure AS (
  SELECT
    address,
    COUNT(DISTINCT sanctioned_address) AS sanctioned_touched,
    COUNT(*) AS transfers_with_sanctioned,
    SUM(amount_usdt) AS usdt_with_sanctioned,
    MAX(block_time) AS last_seen
  FROM hop
  GROUP BY address
),
largest AS (
  -- The single largest on-chain transfer behind each exposure, cited as evidence.
  SELECT address, tx_hash, sanctioned_address, amount_usdt, block_time,
         ROW_NUMBER() OVER (PARTITION BY address ORDER BY amount_usdt DESC, tx_hash) AS rn
  FROM hop
)
SELECT
  'R02' AS rule_id,
  t.customer_id,
  t.tx_id AS anchor_tx_id,
  CASE WHEN e.usdt_with_sanctioned >= p.high_exposure_usdt THEN 'high' ELSE 'medium' END AS severity,
  printf('%s of $%,.2f %s an address that moved %,.0f USDT with %d sanctioned address%s',
         CASE t.direction WHEN 'deposit' THEN 'Deposit' ELSE 'Withdrawal' END,
         t.usd_value,
         CASE t.direction WHEN 'deposit' THEN 'from' ELSE 'to' END,
         e.usdt_with_sanctioned, e.sanctioned_touched,
         CASE e.sanctioned_touched WHEN 1 THEN '' ELSE 'es' END) AS summary,
  json_object(
    'counterparty', t.counterparty_address,
    'sanctioned_touched', e.sanctioned_touched,
    'transfers_with_sanctioned', e.transfers_with_sanctioned,
    'usdt_with_sanctioned', round(e.usdt_with_sanctioned, 2),
    'last_seen', e.last_seen,
    'example_tx_hash', l.tx_hash,
    'example_sanctioned_address', l.sanctioned_address,
    'example_amount_usdt', l.amount_usdt,
    'example_block_time', l.block_time
  ) AS evidence
FROM transfers AS t
JOIN exposure AS e ON e.address = t.counterparty_address
JOIN largest AS l ON l.address = e.address AND l.rn = 1
CROSS JOIN params AS p
WHERE NOT EXISTS (SELECT 1 FROM sanctioned_addresses AS s WHERE s.address = t.counterparty_address);
