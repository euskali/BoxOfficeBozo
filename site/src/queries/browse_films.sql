-- browse_films(letter, limit, offset)
--
-- Films by first letter, for the A-Z bar. A leading "The ", "A " or "An " doesn't count ("The
-- Terminator" files under T), accents are ignored, and titles that don't start with a letter
-- file under '#'.
--   $1 letter   'A'..'Z' or '#'
--   $2 limit    $3 offset: paging
--
-- gross is the film's latest nominal total; matching counts the films under the letter.
WITH keyed AS (
    SELECT title_id, title, year, distributor,
           lower(strip_accents(regexp_replace(title, '^(The|A|An) ', ''))) AS sort_title
    FROM titles
),
lettered AS (
    SELECT *,
           CASE WHEN regexp_matches(left(sort_title, 1), '^[a-z]$') THEN upper(left(sort_title, 1))
                ELSE '#' END AS letter
    FROM keyed
),
gross AS (
    SELECT title_id, arg_max_null(cume_nominal, as_of) AS gross
    FROM title_cume
    GROUP BY title_id
)
SELECT l.title_id, l.title, l.year, l.distributor, g.gross, count(*) OVER () AS matching
FROM lettered AS l
LEFT JOIN gross AS g USING (title_id)
WHERE l.letter = upper(CAST($1 AS VARCHAR))
ORDER BY l.sort_title, l.year, l.title_id
LIMIT CAST($2 AS BIGINT) OFFSET CAST($3 AS BIGINT)
