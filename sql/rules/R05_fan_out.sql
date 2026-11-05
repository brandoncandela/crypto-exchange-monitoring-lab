-- R05 Fan-out to new addresses (peel / dispersal)
-- One deposit followed within a day by withdrawals to many addresses the
-- customer has never paid before. Dispersal to fresh wallets breaks the trail
-- and is a typical layering step; payroll and payouts look similar, so the
-- alert shows the customer's segment and expected activity.
WITH params AS (
  SELECT 5 AS min_new_addresses, 24 AS window_hours, 0.5 AS min_share_out, 1000.0 AS min_deposit_usd
),
fresh AS (
  -- Withdrawals to an address with no earlier transfer from the same customer.
  SELECT w.*
  FROM transfers AS w
  WHERE w.direction = 'withdrawal'
    AND NOT EXISTS (
      SELECT 1 FROM transfers AS prior
      WHERE prior.customer_id = w.customer_id
        AND prior.counterparty_address = w.counterparty_address
        AND prior.occurred_at < w.occurred_at
    )
)
SELECT
  'R05' AS rule_id,
  d.customer_id,
  d.tx_id AS anchor_tx_id,
  'medium' AS severity,
  printf('$%,.2f deposit followed by withdrawals to %d new addresses within %d hours ($%,.2f)',
         d.usd_value, COUNT(DISTINCT f.counterparty_address), p.window_hours, SUM(f.usd_value)) AS summary,
  json_object(
    'deposit_usd', round(d.usd_value, 2),
    'new_addresses', COUNT(DISTINCT f.counterparty_address),
    'dispersed_usd', round(SUM(f.usd_value), 2),
    'withdrawal_tx_ids', json_group_array(f.tx_id)
  ) AS evidence
FROM transfers AS d
CROSS JOIN params AS p
JOIN fresh AS f
  ON f.customer_id = d.customer_id
 AND f.occurred_at > d.occurred_at
 AND f.occurred_at <= datetime(d.occurred_at, '+' || p.window_hours || ' hours')
WHERE d.direction = 'deposit'
  AND d.usd_value >= p.min_deposit_usd
GROUP BY d.tx_id
HAVING COUNT(DISTINCT f.counterparty_address) >= p.min_new_addresses
   AND SUM(f.usd_value) >= p.min_share_out * d.usd_value;
