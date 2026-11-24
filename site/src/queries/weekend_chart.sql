-- weekend_chart(on_date)
--
-- The weekend chart as charted, for the latest weekend ending on or before a date.
--   $1 on_date    DATE ('YYYY-MM-DD'); any day snaps back to the weekend before it
--
-- last_rank and last_weekend_gross are the release's rank and weekend gross on the previous
-- chart when that chart ended within 10 days (a holiday chart can end on a Monday), else NULL.
-- prev_weekend_end and next_weekend_end are the charts either side of this one (NULL at the
-- ends), for paging. title is the film's (titles.parquet); charted_title is the release's title
-- as the chart printed it. capture_url is the archived page a row came from (NULL for stat695
-- rows).
WITH chosen AS (
    SELECT max(weekend_end) AS w FROM snapshots WHERE weekend_end <= CAST($1 AS DATE)
),
previous AS (
    SELECT max(s.weekend_end) AS w
    FROM snapshots AS s, chosen AS c
    WHERE s.weekend_end < c.w
),
following AS (
    SELECT min(s.weekend_end) AS w
    FROM snapshots AS s, chosen AS c
    WHERE s.weekend_end > c.w
),
last_week AS (
    SELECT s.release_id, min(s.rank) AS rank, max(s.weekend_gross) AS weekend_gross
    FROM snapshots AS s, chosen AS c, previous AS p
    WHERE s.weekend_end = p.w AND p.w >= c.w - INTERVAL 10 DAY
    GROUP BY s.release_id
)
SELECT s.weekend_end, s.rank, l.rank AS last_rank, s.release_id, s.title_id, t.title,
       r.title AS charted_title, r.label, r.distributor, s.weekend_gross,
       l.weekend_gross AS last_weekend_gross, s.theaters, s.total_gross, s.weeks, s.is_estimate,
       s.source, s.capture_url, p.w AS prev_weekend_end, f.w AS next_weekend_end
FROM snapshots AS s
JOIN chosen AS c ON s.weekend_end = c.w
CROSS JOIN previous AS p
CROSS JOIN following AS f
LEFT JOIN last_week AS l USING (release_id)
LEFT JOIN releases AS r USING (release_id)
LEFT JOIN titles AS t ON t.title_id = s.title_id
ORDER BY s.rank NULLS LAST, s.weekend_gross DESC NULLS LAST, s.release_id
