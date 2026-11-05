-- R01 Direct sanctions exposure
-- A deposit from, or withdrawal to, an address listed on the OFAC SDN list.
-- Any amount alerts: there is no de minimis threshold for sanctions exposure.
SELECT
  'R01' AS rule_id,
  t.customer_id,
  t.tx_id AS anchor_tx_id,
  'critical' AS severity,
  printf('%s of $%,.2f %s a sanctioned address (%s, %s)',
         CASE t.direction WHEN 'deposit' THEN 'Deposit' ELSE 'Withdrawal' END,
         t.usd_value,
         CASE t.direction WHEN 'deposit' THEN 'from' ELSE 'to' END,
         s.sdn_name, s.program) AS summary,
  json_object(
    'counterparty', t.counterparty_address,
    'sdn_id', s.sdn_id,
    'sdn_name', s.sdn_name,
    'program', s.program,
    'listed_asset', s.asset
  ) AS evidence
FROM transfers AS t
JOIN sanctioned_addresses AS s ON s.address = t.counterparty_address
-- One alert per transfer even if the address appears under several SDN entries.
GROUP BY t.tx_id;
