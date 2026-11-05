-- R06 Travel Rule information gap
-- A withdrawal at or above $3,000 with no beneficiary information recorded.
-- This is a compliance-process alert rather than a suspicion indicator: the
-- fix is usually to collect the information, not to file a report.
WITH params AS (
  SELECT 3000.0 AS threshold_usd
)
SELECT
  'R06' AS rule_id,
  t.customer_id,
  t.tx_id AS anchor_tx_id,
  'low' AS severity,
  printf('$%,.2f withdrawal with no beneficiary information recorded', t.usd_value) AS summary,
  json_object('withdrawal_usd', round(t.usd_value, 2), 'counterparty', t.counterparty_address) AS evidence
FROM transfers AS t
CROSS JOIN params AS p
WHERE t.direction = 'withdrawal'
  AND t.usd_value >= p.threshold_usd
  AND (t.beneficiary_name IS NULL OR trim(t.beneficiary_name) = '');
