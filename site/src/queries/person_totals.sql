-- person_totals(as_of, role, measure, top_billed, limit, offset, person_id)
--
-- Career totals on a date, ranked among everyone credited in the same role.
--   $1 as_of       DATE ('YYYY-MM-DD')
--   $2 role        'director' | 'actor'
--   $3 measure     'nominal' | 'cpi' | 'admissions'
--   $4 top_billed  actors count only films they're billed in the top N of (default 4);
--                  every credited director counts
--   $5 limit       $6 offset: paging
--   $7 person_id   only this person (NULL: everyone). That's person_rank: their rank and total
--                  among `peers` people with a total on that date.
--
-- A career total is the sum, over the person's counted films, of each film's latest total on or
-- before the date (leaderboard.sql's value, found the same way). `titles` counts those films.
-- Ties share a rank.
WITH latest AS (
    SELECT l.*
    FROM (
        SELECT title_id,
               arg_max_null(cume_nominal, as_of) AS cume_nominal,
               arg_max_null(cume_cpi, as_of) AS cume_cpi,
               arg_max_null(cume_admissions, as_of) AS cume_admissions
        FROM title_cume
        WHERE as_of <= CAST($1 AS DATE)
        GROUP BY title_id
    ) AS l
    JOIN titles AS t USING (title_id)
),
counted AS (
    SELECT DISTINCT person_id, title_id
    FROM credits
    WHERE role = CASE WHEN CAST($2 AS VARCHAR) IN ('director', 'actor') THEN CAST($2 AS VARCHAR)
                      ELSE error('unknown role: ' || CAST($2 AS VARCHAR)) END
      AND (role = 'director' OR billing <= CAST($4 AS INTEGER))
),
valued AS (
    SELECT k.person_id,
           CASE CAST($3 AS VARCHAR)
               WHEN 'nominal' THEN CAST(l.cume_nominal AS DOUBLE)
               WHEN 'cpi' THEN l.cume_cpi
               WHEN 'admissions' THEN l.cume_admissions
               ELSE error('unknown measure: ' || CAST($3 AS VARCHAR))
           END AS value
    FROM counted AS k
    JOIN latest AS l USING (title_id)
),
totals AS (
    SELECT person_id, sum(value) AS value, count(value) AS titles
    FROM valued
    WHERE value IS NOT NULL
    GROUP BY person_id
),
ranked AS (
    SELECT *, RANK() OVER (ORDER BY value DESC) AS rank, count(*) OVER () AS peers
    FROM totals
)
SELECT r.rank, r.person_id, p.name, p.imdb_id, r.value, r.titles, r.peers
FROM ranked AS r
LEFT JOIN people AS p USING (person_id)
WHERE CAST($7 AS VARCHAR) IS NULL OR r.person_id = CAST($7 AS VARCHAR)
ORDER BY r.rank, r.person_id
LIMIT CAST($5 AS BIGINT) OFFSET CAST($6 AS BIGINT)
