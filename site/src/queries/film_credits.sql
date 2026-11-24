-- film_credits(title_id)
--
-- A film's directors, then its cast in billing order (credits.parquet), with names.
--   $1 title_id
--
-- billing is 1 for the top-billed actor and NULL for directors; billing_source says where an
-- actor's place came from ('p1545': a Wikidata series ordinal; 'statement_order').
SELECT c.role, c.billing, c.billing_source, c.person_id, p.name, p.imdb_id
FROM credits AS c
LEFT JOIN people AS p USING (person_id)
WHERE c.title_id = CAST($1 AS VARCHAR)
ORDER BY CASE c.role WHEN 'director' THEN 0 ELSE 1 END, c.billing NULLS LAST, p.name, c.person_id
