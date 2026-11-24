-- film_rank_timeline(title_id, measure)
--
-- A film's all-time rank from its first appearance on, as a step series: each row holds from
-- as_of until the next row, and there's a row wherever the rank or the film's value changes.
--   $1 title_id
--   $2 measure    'nominal' | 'cpi' | 'admissions'
--
-- rank is what leaderboard.sql gives as all_time_rank on any date: 1 + the number of titles
-- whose value is higher (ties share a rank). While the film has no value in the measure (it
-- couldn't be priced), rank and value are NULL, as the leaderboard leaves it out.
--
-- How: each title's cumulative totals are a run of constant segments [a, b), one per
-- title_cume row. While another title's segment overlaps one of the film's segments and is
-- higher than it, the film's rank is one lower. So each such overlap adds +1 where it starts
-- and -1 where it ends, and a running sum of those events in date order is the film's rank.
WITH valued AS (
    SELECT title_id, as_of,
           CASE CAST($2 AS VARCHAR)
               WHEN 'nominal' THEN CAST(cume_nominal AS DOUBLE)
               WHEN 'cpi' THEN cume_cpi
               WHEN 'admissions' THEN cume_admissions
               ELSE error('unknown measure: ' || CAST($2 AS VARCHAR))
           END AS value
    FROM title_cume
),
segments AS (
    SELECT title_id, as_of AS a,
           lead(as_of, 1, DATE '9999-12-31') OVER (PARTITION BY title_id ORDER BY as_of) AS b,
           value
    FROM valued
),
film AS (
    SELECT a, b, value FROM segments WHERE title_id = CAST($1 AS VARCHAR)
),
above AS (
    SELECT greatest(s.a, f.a) AS start, least(s.b, f.b) AS stop
    FROM segments AS s
    JOIN film AS f ON s.a < f.b AND s.b > f.a AND s.value > f.value
    WHERE s.title_id <> CAST($1 AS VARCHAR)
),
events AS (
    SELECT start AS day, 1 AS delta FROM above
    UNION ALL
    SELECT stop, -1 FROM above WHERE stop < DATE '9999-12-31'
    UNION ALL
    SELECT a, 0 FROM film
),
steps AS (
    SELECT day, CAST(1 + sum(sum(delta)) OVER (ORDER BY day) AS BIGINT) AS rank
    FROM events
    GROUP BY day
),
valued_steps AS (
    SELECT s.day AS as_of, CASE WHEN f.value IS NOT NULL THEN s.rank END AS rank, f.value
    FROM steps AS s
    ASOF JOIN film AS f ON s.day >= f.a
),
changes AS (
    SELECT *, row_number() OVER (ORDER BY as_of) AS n,
           lag(rank) OVER (ORDER BY as_of) AS prev_rank, lag(value) OVER (ORDER BY as_of) AS prev_value
    FROM valued_steps
)
SELECT as_of, rank, value
FROM changes
WHERE n = 1 OR rank IS DISTINCT FROM prev_rank OR value IS DISTINCT FROM prev_value
ORDER BY as_of
