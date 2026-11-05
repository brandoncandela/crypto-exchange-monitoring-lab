-- R03 Pass-through (rapid in and out)
-- Most of a deposit leaves again within an hour. Funds that only touch the
-- exchange briefly are a common layering step. Expected for some customers
-- (OTC desks, market makers), which is why KYC segment is shown in the alert.
WITH params AS (
  SELECT 60 AS window_minutes, 0.80 AS min_share_out, 1000.0 AS min_deposit_usd
)
SELECT
  'R03' AS rule_id,
  d.customer_id,
  d.tx_id AS anchor_tx_id,
  'medium' AS severity,
  printf('$%,.2f deposit; %.0f%% withdrawn within %d minutes across %d withdrawal%s',
         d.usd_value, 100.0 * SUM(w.usd_value) / d.usd_value, p.window_minutes,
         COUNT(w.tx_id), CASE COUNT(w.tx_id) WHEN 1 THEN '' ELSE 's' END) AS summary,
  json_object(
    'deposit_usd', round(d.usd_value, 2),
    'withdrawn_usd', round(SUM(w.usd_value), 2),
    'minutes_to_last_withdrawal',
      CAST(round((julianday(MAX(w.occurred_at)) - julianday(d.occurred_at)) * 1440) AS INTEGER),
    'withdrawal_tx_ids', json_group_array(w.tx_id)
  ) AS evidence
FROM transfers AS d
CROSS JOIN params AS p
JOIN transfers AS w
  ON w.customer_id = d.customer_id
 AND w.direction = 'withdrawal'
 AND w.occurred_at > d.occurred_at
 AND w.occurred_at <= datetime(d.occurred_at, '+' || p.window_minutes || ' minutes')
WHERE d.direction = 'deposit'
  AND d.usd_value >= p.min_deposit_usd
GROUP BY d.tx_id
HAVING SUM(w.usd_value) >= p.min_share_out * d.usd_value;
