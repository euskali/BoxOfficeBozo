-- person(person_id)
--
-- One person (people.parquet) with how many films they're credited on in each role.
--   $1 person_id   a Wikidata QID
SELECT p.person_id, p.name, p.imdb_id,
       count(c.title_id) FILTER (WHERE c.role = 'director') AS directed,
       count(c.title_id) FILTER (WHERE c.role = 'actor') AS acted
FROM people AS p
LEFT JOIN credits AS c USING (person_id)
WHERE p.person_id = CAST($1 AS VARCHAR)
GROUP BY p.person_id, p.name, p.imdb_id
