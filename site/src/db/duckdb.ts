import type { AsyncDuckDB } from '@duckdb/duckdb-wasm'

let dbPromise: Promise<AsyncDuckDB> | undefined

/**
 * Lazily creates (once) a DuckDB-WASM instance. The library, its worker and
 * its wasm binaries are all self-hosted by Vite (`?url` imports), and so is the
 * Parquet extension DuckDB loads at runtime (scripts/duckdb-extensions.mjs puts
 * it in public/duckdb-extensions), so the site never calls a CDN at runtime.
 * Nothing here runs until getDb() is called.
 */
export function getDb(): Promise<AsyncDuckDB> {
  dbPromise ??= createDb().catch((err: unknown) => {
    dbPromise = undefined // allow a retry after a failure
    throw err
  })
  return dbPromise
}

async function createDb(): Promise<AsyncDuckDB> {
  const duckdb = await import('@duckdb/duckdb-wasm')
  const [mvpWasm, mvpWorker, ehWasm, ehWorker] = await Promise.all([
    import('@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url'),
    import('@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url'),
    import('@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url'),
    import('@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url'),
  ])
  const bundles = {
    mvp: { mainModule: mvpWasm.default, mainWorker: mvpWorker.default },
    eh: { mainModule: ehWasm.default, mainWorker: ehWorker.default },
  }
  const bundle = await duckdb.selectBundle(bundles)
  const worker = new Worker(bundle.mainWorker!)
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), worker)
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker)
  // Extensions (read_parquet's) load from this site, not extensions.duckdb.org.
  const repository = new URL(`${import.meta.env.BASE_URL}duckdb-extensions`, window.location.href).href
  const conn = await db.connect()
  try {
    await conn.query(`SET custom_extension_repository = '${repository.replace(/'/g, "''")}'`)
  } finally {
    await conn.close()
  }
  return db
}
