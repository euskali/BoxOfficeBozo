-- leaderboard(as_of, measure, limit, offset, from_year, to_year, title_id)
--
-- Every title's latest totals on or before a date, ranked all-time by one measure.
--   $1 as_of      DATE ('YYYY-MM-DD'): the date to rank on
--   $2 measure    'nominal' | 'cpi' | 'admissions'
--   $3 limit      $4 offset: paging over the rows that pass the filters
--   $5 from_year  $6 to_year: only titles released in these years (NULL: no bound)
--   $7 title_id   only this title (NULL: every title), for a film's rank on a date
--
-- all_time_rank ranks every title that has a value on that date; rank ranks the rows that
-- pass the filters, and `matching` counts them. Ties share a rank (RANK()), then sort by
-- title_id. cume_cpi is in 1982-84 dollars (cpi_factor.sql converts). A title whose total
-- includes a pre-1982 baseline has baseline = true, and baseline_is_rental says whether that
-- baseline is film rentals rather than box office gross.
--
-- The site runs this file in DuckDB-WASM and the Python tests run it in duckdb
-- (boffo_etl/queries.py): one source of truth.
--
-- "Latest row on or before the date" is an arg_max over title_cume rather than an ASOF JOIN:
-- the same rows, about five times faster in DuckDB-WASM (no sort). arg_max_null, not arg_max,
-- so a measure that is NULL on the latest row stays NULL instead of falling back to an older one.
WITH latest AS (
    SELECT l.*, t.title, t.year, t.baseline_is_rental
    FROM (
        SELECT title_id, max(as_of) AS as_of,
               arg_max_null(cume_nominal, as_of) AS cume_nominal,
               arg_max_null(cume_cpi, as_of) AS cume_cpi,
               arg_max_null(cume_admissions, as_of) AS cume_admissions,
               arg_max_null(baseline, as_of) AS baseline
        FROM title_cume
        WHERE as_of <= CAST($1 AS DATE)
        GROUP BY title_id
    ) AS l
    JOIN titles AS t USING (title_id)
),
valued AS (
    SELECT *,
           CASE CAST($2 AS VARCHAR)
               WHEN 'nominal' THEN CAST(cume_nominal AS DOUBLE)
               WHEN 'cpi' THEN cume_cpi
               WHEN 'admissions' THEN cume_admissions
               ELSE error('unknown measure: ' || CAST($2 AS VARCHAR))
           END AS value
    FROM latest
),
ranked AS (
    SELECT *, RANK() OVER (ORDER BY value DESC) AS all_time_rank
    FROM valued
    WHERE value IS NOT NULL
),
filtered AS (
    SELECT *
    FROM ranked
    WHERE (CAST($5 AS INTEGER) IS NULL OR year >= CAST($5 AS INTEGER))
      AND (CAST($6 AS INTEGER) IS NULL OR year <= CAST($6 AS INTEGER))
      AND (CAST($7 AS VARCHAR) IS NULL OR title_id = CAST($7 AS VARCHAR))
)
SELECT RANK() OVER (ORDER BY value DESC) AS rank, all_time_rank, title_id, title, year, value,
       cume_nominal, cume_cpi, cume_admissions, baseline, baseline_is_rental,
       as_of AS last_change, count(*) OVER () AS matching
FROM filtered
ORDER BY rank, title_id
LIMIT CAST($3 AS BIGINT) OFFSET CAST($4 AS BIGINT)
