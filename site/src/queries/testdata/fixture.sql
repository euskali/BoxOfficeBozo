-- A tiny synthetic dataset for the query tests: fictional films, people and numbers, never
-- deployed. etl/tests/test_queries.py (duckdb) and src/queries/queries.test.ts (DuckDB-WASM)
-- both load it, so the same SQL is checked on the same input in both engines.
--
-- Nominal totals by date (ranks in brackets):
--   1982-01-01  echo 250 (baseline)            [echo 1]
--   1990-01-07  alpha 100                      [echo 1, alpha 2]
--   1990-01-14  alpha 300                      [alpha 1, echo 2]
--   1991-01-06  bravo 200, charlie 50          [alpha 1, echo 2, bravo 3, charlie 4]
--   1991-01-13  bravo 400, charlie 300         [bravo 1, alpha 2, charlie 2, echo 4]
--   1993-01-03  foxtrot 80                     [... foxtrot 5]
--   1993-01-10  foxtrot 120                    [... foxtrot 5]
--   1995-06-04  delta 1000                     [delta 1, bravo 2, alpha 3, charlie 3, echo 5, foxtrot 6]
-- foxtrot's second row has no CPI dollars or admissions (unpriceable), so from 1993-01-10 it has
-- no value in those measures: the leaderboard leaves it out and its timeline rank is NULL.
CREATE TABLE titles (title_id VARCHAR, title VARCHAR, year INTEGER, baseline_is_rental BOOLEAN);
INSERT INTO titles VALUES
    ('test_alpha', 'Test Film Alpha', 1990, NULL),
    ('test_bravo', 'Test Film Bravo', 1991, NULL),
    ('test_charlie', 'Test Film Charlie', 1991, NULL),
    ('test_delta', 'Test Film Delta', 1995, NULL),
    ('test_echo', 'Test Film Echo', 1975, true),
    ('test_foxtrot', 'Test Film Foxtrot', 1993, NULL);

CREATE TABLE title_cume (title_id VARCHAR, as_of DATE, cume_nominal BIGINT, cume_cpi DOUBLE,
                         cume_admissions DOUBLE, baseline BOOLEAN);
INSERT INTO title_cume VALUES
    ('test_echo', DATE '1982-01-01', 250, 600.0, 200.0, true),
    ('test_alpha', DATE '1990-01-07', 100, 150.0, 50.0, false),
    ('test_alpha', DATE '1990-01-14', 300, 450.0, 150.0, false),
    ('test_bravo', DATE '1991-01-06', 200, 180.0, 80.0, false),
    ('test_bravo', DATE '1991-01-13', 400, 360.0, 160.0, false),
    ('test_charlie', DATE '1991-01-06', 50, 45.0, 20.0, false),
    ('test_charlie', DATE '1991-01-13', 300, 270.0, 120.0, false),
    ('test_foxtrot', DATE '1993-01-03', 80, 90.0, 30.0, false),
    ('test_foxtrot', DATE '1993-01-10', 120, NULL, NULL, false),
    ('test_delta', DATE '1995-06-04', 1000, 700.0, 250.0, false);

CREATE TABLE people (person_id VARCHAR, imdb_id VARCHAR, name VARCHAR);
INSERT INTO people VALUES
    ('P1', NULL, 'Test Director One'), ('P2', NULL, 'Test Director Two'),
    ('P3', NULL, 'Test Director Three'), ('P10', NULL, 'Test Actor Ten'),
    ('P11', NULL, 'Test Actor Eleven'), ('P12', NULL, 'Test Actor Twelve'),
    ('P13', NULL, 'Test Actor Thirteen');

CREATE TABLE credits (title_id VARCHAR, person_id VARCHAR, role VARCHAR, billing INTEGER,
                      billing_source VARCHAR);
INSERT INTO credits VALUES
    ('test_alpha', 'P1', 'director', NULL, NULL),
    ('test_alpha', 'P10', 'actor', 1, 'p1545'),
    ('test_alpha', 'P11', 'actor', 2, 'p1545'),
    ('test_bravo', 'P2', 'director', NULL, NULL),
    ('test_bravo', 'P11', 'actor', 1, 'statement_order'),
    ('test_bravo', 'P10', 'actor', 5, 'statement_order'),
    ('test_charlie', 'P1', 'director', NULL, NULL),
    ('test_charlie', 'P12', 'actor', 3, 'statement_order'),
    ('test_charlie', 'P13', 'actor', NULL, NULL),
    ('test_delta', 'P2', 'director', NULL, NULL),
    ('test_delta', 'P1', 'director', NULL, NULL),
    ('test_delta', 'P10', 'actor', 4, 'statement_order'),
    ('test_echo', 'P3', 'director', NULL, NULL),
    ('test_echo', 'P12', 'actor', 1, 'statement_order');

CREATE TABLE releases (release_id VARCHAR, title_id VARCHAR, title VARCHAR, label VARCHAR,
                       distributor VARCHAR);
INSERT INTO releases VALUES
    ('rel_alpha', 'test_alpha', 'Test Film Alpha', NULL, 'Fictional Pictures'),
    ('rel_bravo', 'test_bravo', 'Test Film Bravo', NULL, 'Imaginary Films'),
    ('rel_charlie', 'test_charlie', 'Test Film Charlie', NULL, 'Fictional Pictures'),
    ('rel_delta', 'test_delta', 'Test Film Delta (Special Edition)', 'Special Edition', 'Imaginary Films');

CREATE TABLE snapshots (weekend_end DATE, release_id VARCHAR, title_id VARCHAR, rank INTEGER,
                        weekend_gross BIGINT, theaters INTEGER, total_gross BIGINT, weeks INTEGER,
                        source VARCHAR, capture_url VARCHAR, is_estimate BOOLEAN);
INSERT INTO snapshots VALUES
    (DATE '1990-01-07', 'rel_alpha', 'test_alpha', 1, 100, 10, 100, 1, 'stat695', NULL, false),
    (DATE '1990-01-14', 'rel_alpha', 'test_alpha', 1, 200, 12, 300, 2, 'stat695', NULL, false),
    (DATE '1991-01-06', 'rel_bravo', 'test_bravo', 1, 200, 20, 200, 1, 'stat695', NULL, false),
    (DATE '1991-01-06', 'rel_charlie', 'test_charlie', 2, 50, 5, 50, 1, 'stat695', NULL, false),
    (DATE '1991-01-13', 'rel_charlie', 'test_charlie', 1, 250, 25, 300, 2, 'stat695', NULL, false),
    (DATE '1991-01-13', 'rel_bravo', 'test_bravo', 2, 200, 20, 400, 2, 'stat695', NULL, false),
    (DATE '1995-06-04', 'rel_delta', 'test_delta', 1, 1000, 30, 1000, 1, 'wayback',
     'https://web.archive.org/web/1/example.invalid/weekend', true);

CREATE TABLE cpi (month DATE, cpi DOUBLE, is_interpolated BOOLEAN);
INSERT INTO cpi VALUES
    (DATE '1990-01-01', 127.4, false),
    (DATE '1991-01-01', 134.6, false),
    (DATE '1995-06-01', 152.5, true);
