import type { AsyncDuckDBConnection } from '@duckdb/duckdb-wasm'
import type { Query } from '../queries'
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
