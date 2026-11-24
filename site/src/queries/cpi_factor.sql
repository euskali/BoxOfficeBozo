-- cpi_factor(on_date)
--
-- Multiply a cume_cpi value (1982-84 dollars) by `factor` for dollars of the month of $1.
--   $1 on_date    DATE ('YYYY-MM-DD'); "today's dollars" is today's date
--
-- A month after the latest published CPI uses the latest index; `month` says which one was
-- used, and is_interpolated flags a month BLS published no index for. No row before 1913.
SELECT month, cpi / 100.0 AS factor, is_interpolated
FROM cpi
WHERE month <= date_trunc('month', CAST($1 AS DATE))
ORDER BY month DESC
LIMIT 1
