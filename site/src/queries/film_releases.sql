-- film_releases(title_id)
--
-- A film's releases (the original run, re-issues, special editions), oldest first, each with its
-- last charted total gross.
--   $1 title_id
SELECT r.release_id, r.label, r.release_date, r.title, r.distributor, r.first_weekend,
       r.last_weekend, r.weekends, r.is_rerelease, r.source, s.total_gross
FROM releases AS r
LEFT JOIN (
    SELECT release_id, arg_max(total_gross, weekend_end) AS total_gross
    FROM snapshots
    WHERE title_id = CAST($1 AS VARCHAR)
    GROUP BY release_id
) AS s USING (release_id)
WHERE r.title_id = CAST($1 AS VARCHAR)
ORDER BY coalesce(r.release_date, r.first_weekend), r.release_id
