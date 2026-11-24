import type { AsyncDuckDB, AsyncDuckDBConnection } from '@duckdb/duckdb-wasm'
import { TABLES, type Query } from '../queries'
import { toRows, type Row } from './rows'

/** Runs one of the shared queries (src/queries) as a prepared statement. */
export async function runQuery(conn: AsyncDuckDBConnection, q: Query): Promise<Row[]> {
  const stmt = await conn.prepare(q.sql)
  try {
    return toRows(await stmt.query(...q.params))
  } finally {
    await stmt.close()
  }
}

/**
 * Loads the site's Parquet tables (public/data, built in CI) into memory under the names the
 * queries use. Each file is read once over HTTP; queries then run without network round trips.
 */
export async function loadTables(
  db: AsyncDuckDB,
  conn: AsyncDuckDBConnection,
  names: readonly string[] = TABLES,
  base = `${import.meta.env.BASE_URL}data/`,
): Promise<void> {
  const { DuckDBDataProtocol } = await import('@duckdb/duckdb-wasm')
  await Promise.all(
    names.map((n) =>
      db.registerFileURL(`${n}.parquet`, new URL(`${base}${n}.parquet`, window.location.href).href, DuckDBDataProtocol.HTTP, false),
    ),
  )
  for (const n of names) {
    await conn.query(`CREATE TABLE IF NOT EXISTS ${n} AS SELECT * FROM read_parquet('${n}.parquet')`)
  }
}
