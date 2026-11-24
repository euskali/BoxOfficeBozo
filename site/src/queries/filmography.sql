-- filmography(person_id, as_of, measure, top_billed)
--
-- A person's credited films, each with its total and all-time rank on a date.
--   $1 person_id
--   $2 as_of       DATE ('YYYY-MM-DD')
--   $3 measure     'nominal' | 'cpi' | 'admissions'
--   $4 top_billed  an actor's film counts toward their career total when they're billed in the
--                  top N of it (person_totals.sql's rule); every directing credit counts
--
-- value and all_time_rank are leaderboard.sql's for that film on that date (NULL before it has
-- a value). counted says whether the credit counts toward person_totals.
WITH latest AS (
    SELECT title_id,
           CASE CAST($3 AS VARCHAR)
               WHEN 'nominal' THEN CAST(arg_max_null(cume_nominal, as_of) AS DOUBLE)
               WHEN 'cpi' THEN arg_max_null(cume_cpi, as_of)
               WHEN 'admissions' THEN arg_max_null(cume_admissions, as_of)
               ELSE error('unknown measure: ' || CAST($3 AS VARCHAR))
           END AS value,
           arg_max_null(baseline, as_of) AS baseline
    FROM title_cume
    WHERE as_of <= CAST($2 AS DATE)
    GROUP BY title_id
),
ranked AS (
    SELECT l.*, RANK() OVER (ORDER BY l.value DESC) AS all_time_rank
    FROM latest AS l
    JOIN titles USING (title_id)
    WHERE l.value IS NOT NULL
)
SELECT c.role, c.billing, c.billing_source,
       coalesce(c.role = 'director' OR c.billing <= CAST($4 AS INTEGER), false) AS counted,
       t.title_id, t.title, t.year, t.release_date, r.value, r.all_time_rank, r.baseline,
       t.baseline_is_rental
FROM credits AS c
JOIN titles AS t USING (title_id)
LEFT JOIN ranked AS r USING (title_id)
WHERE c.person_id = CAST($1 AS VARCHAR)
ORDER BY t.year, t.release_date NULLS LAST, t.title, t.title_id,
         CASE c.role WHEN 'director' THEN 0 ELSE 1 END
