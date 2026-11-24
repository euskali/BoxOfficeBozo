-- latest_date()
--
-- The newest date in title_cume: the last weekend the data covers. Pages that rank "as of" a
-- date default to it.
SELECT max(as_of) AS as_of FROM title_cume
