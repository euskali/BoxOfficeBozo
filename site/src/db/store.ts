import type { AsyncDuckDB, AsyncDuckDBConnection } from '@duckdb/duckdb-wasm'
import { DERIVED, type DerivedName, type Query, type TableName } from '../queries'
import { getDb } from './duckdb'
import { runQuery } from './query'
import type { Row } from './rows'

/**
 * The site's data, loaded on demand: the DuckDB-WASM engine and each Parquet table (public/data)
 * are fetched the first time a query needs them, then kept in memory. Loading reports progress
 * for the "Loading... please wait" box.
 */

export interface ManifestTable {
  name: string
  bytes: number
  rows?: number
  sha256?: string
}

export interface Manifest {
  built_at?: string
  git_sha?: string | null
  /** True for `make sample-data` output: fictional films, never deployed. */
  sample?: boolean
  tables: ManifestTable[]
}

export interface LoadProgress {
  /** Something is loading. */
  busy: boolean
  /** Progress units (bytes; the engine counts as a fixed weight). */
  done: number
  total: number
  /** What's still loading, e.g. ["the database engine", "title_cume"]. */
  pending: string[]
  /** Megabytes of table data in this round, for the progress text. */
  tableBytes: number
}

/** How much the engine counts for in the progress bar, next to the tables' bytes. */
const ENGINE_WEIGHT = 6_000_000
export const ENGINE_TASK = 'the database engine'

const BASE = `${import.meta.env.BASE_URL}data/`

interface Task {
  label: string
  weight: number
  done: number
  finished: boolean
  isTable: boolean
}

let tasks: Task[] = []
let progress: LoadProgress = { busy: false, done: 0, total: 0, pending: [], tableBytes: 0 }
const listeners = new Set<() => void>()

function publish(): void {
  progress = {
    busy: tasks.some((t) => !t.finished),
    done: tasks.reduce((s, t) => s + t.done, 0),
    total: tasks.reduce((s, t) => s + t.weight, 0),
    pending: tasks.filter((t) => !t.finished).map((t) => t.label),
    tableBytes: tasks.filter((t) => t.isTable).reduce((s, t) => s + t.weight, 0),
  }
  for (const l of listeners) l()
}

function startTask(label: string, weight: number, isTable: boolean): Task {
  if (tasks.every((t) => t.finished)) tasks = [] // a new round of loading
  const task: Task = { label, weight, done: 0, finished: false, isTable }
  tasks.push(task)
  publish()
  return task
}

function finishTask(task: Task): void {
  task.done = task.weight
  task.finished = true
  publish()
}

export function subscribeProgress(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getProgress(): LoadProgress {
  return progress
}

/**
 * Resolves once the page has loaded and shown its first content, so the heavy downloads never
 * compete with the first render: every page's own text paints first, then the data arrives.
 */
let paintGate: Promise<void> | undefined
function afterFirstPaint(): Promise<void> {
  paintGate ??= new Promise<void>((resolve) => {
    let done = false
    const go = () => {
      if (done) return
      done = true
      setTimeout(resolve, 0)
    }
    const painted = () => performance.getEntriesByName('first-contentful-paint').length > 0
    const afterLoad = () => {
      if (painted()) return go()
      try {
        new PerformanceObserver((list, obs) => {
          if (list.getEntriesByName('first-contentful-paint').length) {
            obs.disconnect()
            go()
          }
        }).observe({ type: 'paint', buffered: true })
      } catch {
        // no paint timing: fall through to the timer
      }
      setTimeout(go, 2000) // never wait longer than this (a background tab may not paint)
    }
    if (document.readyState === 'complete') afterLoad()
    else window.addEventListener('load', afterLoad, { once: true })
  })
  return paintGate
}

let manifest: Promise<Manifest | null> | undefined

/** public/data/manifest.json (table sizes and checksums), or null if it can't be read. */
export function getManifest(): Promise<Manifest | null> {
  manifest ??= fetch(`${BASE}manifest.json`, { cache: 'no-cache' })
    .then((r) => (r.ok ? (r.json() as Promise<Manifest>) : null))
    .catch(() => null)
  return manifest
}

interface Engine {
  db: AsyncDuckDB
  conn: AsyncDuckDBConnection
}

let engine: Promise<Engine> | undefined

function getEngine(): Promise<Engine> {
  engine ??= (async () => {
    await afterFirstPaint()
    const task = startTask(ENGINE_TASK, ENGINE_WEIGHT, false)
    try {
      const db = await getDb()
      return { db, conn: await db.connect() }
    } finally {
      finishTask(task)
    }
  })().catch((err: unknown) => {
    engine = undefined // allow a retry
    throw err
  })
  return engine
}

async function download(url: string, onBytes: (n: number) => void): Promise<Uint8Array> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Couldn't download ${url} (HTTP ${res.status})`)
  if (!res.body) {
    const all = new Uint8Array(await res.arrayBuffer())
    onBytes(all.length)
    return all
  }
  const reader = res.body.getReader()
  const chunks: Uint8Array[] = []
  let length = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    chunks.push(value)
    length += value.length
    onBytes(value.length)
  }
  const out = new Uint8Array(length)
  let offset = 0
  for (const c of chunks) {
    out.set(c, offset)
    offset += c.length
  }
  return out
}

async function loadTable(name: TableName): Promise<void> {
  await afterFirstPaint()
  const entry = (await getManifest())?.tables.find((t) => t.name === name)
  const task = startTask(name, entry?.bytes ?? 1_000_000, true)
  try {
    // The checksum in the query string makes a rebuilt table a new URL, past any cached copy.
    const version = entry?.sha256 ? `?v=${entry.sha256.slice(0, 16)}` : ''
    const url = new URL(`${BASE}${name}.parquet${version}`, window.location.href).href
    const bytes = await download(url, (n) => {
      task.done = Math.min(task.weight, task.done + n)
      publish()
    })
    const { db, conn } = await getEngine()
    const file = `${name}.parquet`
    await db.registerFileBuffer(file, bytes)
    await conn.query(`CREATE TABLE IF NOT EXISTS ${name} AS SELECT * FROM read_parquet('${file}')`)
    await db.dropFile(file)
  } finally {
    finishTask(task)
  }
}

async function buildDerived(name: DerivedName): Promise<void> {
  const derived = DERIVED[name]
  await Promise.all(derived.from.map((t) => ensure(t)))
  const { conn } = await getEngine()
  await conn.query(derived.sql)
}

const loads = new Map<string, Promise<void>>()

/** Loads a table (once), or builds a derived one from its sources. */
export function ensure(name: TableName | DerivedName): Promise<void> {
  let p = loads.get(name)
  if (!p) {
    p = (name in DERIVED ? buildDerived(name as DerivedName) : loadTable(name as TableName)).catch((err: unknown) => {
      loads.delete(name) // allow a retry
      throw err
    })
    loads.set(name, p)
  }
  return p
}

/** Runs a shared query, loading whatever it reads first. */
export async function run(q: Query): Promise<Row[]> {
  await Promise.all(q.tables.map((t) => ensure(t)))
  const { conn } = await getEngine()
  return runQuery(conn, q)
}

/** Starts loading what `q` reads, without running it (e.g. when the search box gets focus). */
export function prefetch(q: Query): void {
  for (const t of q.tables) ensure(t).catch(() => {})
}
