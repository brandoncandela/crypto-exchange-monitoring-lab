-- R04 Structuring below the Travel Rule threshold
-- Repeated withdrawals just under $3,000, the U.S. threshold above which
-- originator and beneficiary information must travel with a transmittal
-- (31 CFR 1010.410(f)). Several in one day that add up to a large amount
-- suggest the customer is splitting a transfer to avoid collection.
WITH params AS (
  SELECT 3000.0 AS threshold_usd, 2500.0 AS band_floor_usd,
         4 AS min_count, 10000.0 AS min_total_usd, 24 AS window_hours
),
near AS (
  SELECT t.*
  FROM transfers AS t CROSS JOIN params AS p
  WHERE t.direction = 'withdrawal'
    AND t.usd_value >= p.band_floor_usd AND t.usd_value < p.threshold_usd
),
clusters AS (
  -- Each near-threshold withdrawal opens a window; count what follows within it.
  SELECT a.customer_id, a.tx_id AS anchor_tx_id, a.occurred_at,
         COUNT(*) AS n, SUM(b.usd_value) AS total_usd,
         json_group_array(b.tx_id) AS tx_ids
  FROM near AS a CROSS JOIN params AS p
  JOIN near AS b
    ON b.customer_id = a.customer_id
   AND b.occurred_at >= a.occurred_at
   AND b.occurred_at < datetime(a.occurred_at, '+' || p.window_hours || ' hours')
  GROUP BY a.tx_id
  HAVING COUNT(*) >= p.min_count AND SUM(b.usd_value) >= p.min_total_usd
),
ranked AS (
  -- Overlapping windows describe the same behavior; keep the largest per customer.
  SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY n DESC, total_usd DESC, occurred_at) AS rn
  FROM clusters
)
SELECT
  'R04' AS rule_id,
  customer_id,
  anchor_tx_id,
  'high' AS severity,
  printf('%d withdrawals between $2,500 and $3,000 within 24 hours, totaling $%,.2f', n, total_usd) AS summary,
  json_object('count', n, 'total_usd', round(total_usd, 2), 'withdrawal_tx_ids', json(tx_ids)) AS evidence
FROM ranked
WHERE rn = 1;
