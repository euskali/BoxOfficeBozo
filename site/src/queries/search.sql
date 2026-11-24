-- search(text, limit)
--
-- Films and people with a word in their name that starts with the search text, best first.
-- Reads search_index (search_index.sql builds it).
--   $1 text    what the visitor typed
--   $2 limit   at most this many films, and at most this many people
--
-- The text is normalised as search_index's names are: lower-cased, no accents, periods and
-- apostrophes dropped, other punctuation read as spaces ("et" finds "E.T.", "extra-terr" finds
-- "Extra-Terrestrial"). match says how well: 0 the whole name (a leading "The", "A" or "An"
-- aside), 1 its start, 2 the start of a later word, 3 its start with spaces ignored
-- ("spiderman" finds "Spider-Man"). Within a match, films sort by their latest nominal gross and
-- people by their number of credits. Films come first, then people. Text with no letters or
-- digits finds nothing.
WITH q AS (
    SELECT trim(regexp_replace(regexp_replace(lower(strip_accents(CAST($1 AS VARCHAR))),
                                              '[.''’]', '', 'g'), '[^a-z0-9]+', ' ', 'g')) AS q
),
hits AS (
    SELECT s.kind, s.id, s.name, s.year, s.detail, s.directed, s.acted, s.weight,
           CASE WHEN s.norm = q.q OR s.bare = q.q THEN 0
                WHEN starts_with(s.norm, q.q) OR starts_with(s.bare, q.q) THEN 1
                WHEN s.spaced LIKE '% ' || q.q || '%' THEN 2
                ELSE 3 END AS match
    FROM search_index AS s, q
    WHERE q.q <> ''
      AND (s.spaced LIKE '% ' || q.q || '%' OR s.squashed LIKE replace(q.q, ' ', '') || '%')
),
ranked AS (
    SELECT *,
           row_number() OVER (PARTITION BY kind
                              ORDER BY match, weight DESC NULLS LAST, name, id) AS n
    FROM hits
)
SELECT kind, id, name, year, detail, directed, acted, match, weight
FROM ranked
WHERE n <= CAST($2 AS BIGINT)
ORDER BY kind, n
