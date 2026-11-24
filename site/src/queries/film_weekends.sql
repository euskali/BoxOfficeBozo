-- film_weekends(title_id)
--
-- Every weekend chart a film appeared on, across all its releases, oldest first.
--   $1 title_id
--
-- last_weekend_gross is the same release's gross on its previous charted weekend when that
-- ended within 10 days, else NULL (as in weekend_chart.sql). label is the release's label
-- (NULL for the original release).
SELECT w.weekend_end, w.release_id, r.label, w.rank, w.weekend_gross,
       CASE WHEN w.prev_end >= w.weekend_end - INTERVAL 10 DAY THEN w.prev_gross END
           AS last_weekend_gross,
       w.theaters, w.total_gross, w.weeks, w.is_estimate, w.source, w.capture_url
FROM (
    SELECT *,
           lag(weekend_end) OVER (PARTITION BY release_id ORDER BY weekend_end) AS prev_end,
           lag(weekend_gross) OVER (PARTITION BY release_id ORDER BY weekend_end) AS prev_gross
    FROM snapshots
    WHERE title_id = CAST($1 AS VARCHAR)
) AS w
LEFT JOIN releases AS r USING (release_id)
ORDER BY w.weekend_end, w.rank NULLS LAST, w.release_id
