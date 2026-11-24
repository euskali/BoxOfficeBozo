-- search_index()
--
-- Builds the search_index table that search.sql reads: one row per film and per person, with
-- the name in the forms search compares. Run once after titles, title_cume, people and credits
-- are loaded; normalising ~80,000 names on every keystroke would be too slow in the browser.
--
-- norm: the name lower-cased and without accents, periods and apostrophes dropped, other
-- punctuation read as spaces ("E.T.: The Extra-Terrestrial" -> "et the extra terrestrial").
-- bare: norm without a leading "the", "a" or "an". spaced: ' ' || norm, so a word start is
-- ' ' || text. squashed: norm without spaces ("spiderman"). weight: a film's latest nominal
-- gross, a person's number of credits. detail: a film's distributor.
CREATE OR REPLACE TABLE search_index AS
WITH films AS (
    SELECT 'film' AS kind, t.title_id AS id, t.title AS name, t.year, t.distributor AS detail,
           CAST(NULL AS BIGINT) AS directed, CAST(NULL AS BIGINT) AS acted,
           CAST(g.gross AS DOUBLE) AS weight
    FROM titles AS t
    LEFT JOIN (
        SELECT title_id, arg_max_null(cume_nominal, as_of) AS gross
        FROM title_cume
        GROUP BY title_id
    ) AS g USING (title_id)
),
people_rows AS (
    SELECT 'person' AS kind, p.person_id AS id, p.name, CAST(NULL AS INTEGER) AS year,
           CAST(NULL AS VARCHAR) AS detail,
           count(c.title_id) FILTER (WHERE c.role = 'director') AS directed,
           count(c.title_id) FILTER (WHERE c.role = 'actor') AS acted,
           CAST(count(c.title_id) AS DOUBLE) AS weight
    FROM people AS p
    LEFT JOIN credits AS c USING (person_id)
    WHERE p.name IS NOT NULL
    GROUP BY p.person_id, p.name
),
named AS (
    SELECT *,
           trim(regexp_replace(regexp_replace(lower(strip_accents(name)), '[.''’]', '', 'g'),
                               '[^a-z0-9]+', ' ', 'g')) AS norm
    FROM (SELECT * FROM films UNION ALL SELECT * FROM people_rows)
)
SELECT kind, id, name, year, detail, directed, acted, weight, norm,
       regexp_replace(norm, '^(the|a|an) ', '') AS bare,
       ' ' || norm AS spaced,
       replace(norm, ' ', '') AS squashed
FROM named
