// The query fixture (src/queries/testdata/fixture.sql) in DuckDB-WASM's Node build, for page tests:
// they render the real pages, and the pages run the real SQL on fictional data.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { DuckDBConnection } from '@duckdb/duckdb-wasm/blocking'
import { toRows, type Row } from '../db/rows'
import { DERIVED, type Query } from '../queries'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)

let conn: Promise<DuckDBConnection> | undefined

async function connect(): Promise<DuckDBConnection> {
  const duckdb = await import('@duckdb/duckdb-wasm/blocking')
  const dist = path.dirname(require.resolve('@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs'))
  const bundles = {
    mvp: { mainModule: path.join(dist, 'duckdb-mvp.wasm'), mainWorker: path.join(dist, 'duckdb-node-mvp.worker.cjs') },
    eh: { mainModule: path.join(dist, 'duckdb-eh.wasm'), mainWorker: path.join(dist, 'duckdb-node-eh.worker.cjs') },
  }
  const db = await duckdb.createDuckDB(bundles, new duckdb.VoidLogger(), duckdb.NODE_RUNTIME)
  await db.instantiate(() => {})
  const c = db.connect()
  c.query(readFileSync(path.join(here, '..', 'queries', 'testdata', 'fixture.sql'), 'utf8'))
  for (const d of Object.values(DERIVED)) c.query(d.sql)
  return c
}

/** Runs a shared query on the fixture, as the site's store would on the real tables. */
export async function runFixture(q: Query): Promise<Row[]> {
  conn ??= connect()
  const c = await conn
  const stmt = c.prepare(q.sql)
  try {
    return toRows(stmt.query(...q.params))
  } finally {
    stmt.close()
  }
}
