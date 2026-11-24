-- film(title_id)
--
-- One film's titles.parquet row, with its releases and charted weekends counted and its latest
-- totals (each measure's value on its last title_cume row; NULL where that row has none).
--   $1 title_id
--
-- first_as_of / last_as_of are its first and last title_cume dates; baseline says its totals
-- include a pre-1982 baseline. No row when the title doesn't exist.
WITH cume AS (
    SELECT title_id, min(as_of) AS first_as_of, max(as_of) AS last_as_of,
           arg_max_null(cume_nominal, as_of) AS cume_nominal,
           arg_max_null(cume_cpi, as_of) AS cume_cpi,
           arg_max_null(cume_admissions, as_of) AS cume_admissions,
           bool_or(baseline) AS baseline
    FROM title_cume
    WHERE title_id = CAST($1 AS VARCHAR)
    GROUP BY title_id
),
rel AS (
    SELECT title_id, count(*) AS releases, CAST(sum(weekends) AS BIGINT) AS weekends,
           min(first_weekend) AS first_weekend, max(last_weekend) AS last_weekend
    FROM releases
    WHERE title_id = CAST($1 AS VARCHAR)
    GROUP BY title_id
)
SELECT t.title_id, t.wikidata_qid, t.title, t.year, t.release_date, t.distributor, t.genres,
       t.mpaa, t.pre1982_baseline_gross, t.baseline_is_rental, t.baseline_source,
       c.first_as_of, c.last_as_of, c.cume_nominal, c.cume_cpi, c.cume_admissions, c.baseline,
       r.releases, r.weekends, r.first_weekend, r.last_weekend
FROM titles AS t
LEFT JOIN cume AS c USING (title_id)
LEFT JOIN rel AS r USING (title_id)
WHERE t.title_id = CAST($1 AS VARCHAR)
