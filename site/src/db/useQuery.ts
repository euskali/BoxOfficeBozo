import { useEffect, useState } from 'react'
import type { Query } from '../queries'
import type { Row } from './rows'
import { run } from './store'

export interface QueryState {
  /** Rows for the current query; while a new one runs, the previous query's rows (see `stale`). */
  rows: Row[] | undefined
  loading: boolean
  /** `rows` belong to an earlier query; the current one is still running. */
  stale: boolean
  error: Error | undefined
}

const MAX_CACHED = 80
const results = new Map<string, Row[]>()
const inflight = new Map<string, Promise<Row[]>>()

function keyOf(q: Query): string {
  return `${q.name}|${JSON.stringify(q.params)}`
}

function remember(key: string, rows: Row[]): void {
  results.delete(key)
  results.set(key, rows)
  if (results.size > MAX_CACHED) results.delete(results.keys().next().value as string)
}

function fetchRows(key: string, q: Query): Promise<Row[]> {
  let p = inflight.get(key)
  if (!p) {
    p = run(q)
      .then((rows) => {
        remember(key, rows)
        return rows
      })
      .finally(() => inflight.delete(key))
    inflight.set(key, p)
  }
  return p
}

/** Forgets cached results (tests). */
export function clearQueryCache(): void {
  results.clear()
  inflight.clear()
}

/** Runs a shared query (src/queries) and re-runs it when its parameters change. null: don't run. */
export function useQuery(q: Query | null): QueryState {
  const key = q ? keyOf(q) : null
  const [state, setState] = useState<{ key: string | null; rows?: Row[]; error?: Error }>({ key: null })

  useEffect(() => {
    if (!q || key === null) return
    if (results.has(key)) {
      // shown from the cache; remember it as the rows to keep while a later query runs
      setState((s) => (s.key === key ? s : { key, rows: results.get(key) }))
      return
    }
    let live = true
    fetchRows(key, q).then(
      (rows) => live && setState({ key, rows }),
      (error: unknown) => live && setState({ key, error: error instanceof Error ? error : new Error(String(error)) }),
    )
    return () => {
      live = false
    }
    // `key` captures everything about `q` that matters, so `q` itself isn't a dependency.
  }, [key])

  if (key === null) return { rows: undefined, loading: false, stale: false, error: undefined }
  const cached = results.get(key)
  if (cached) return { rows: cached, loading: false, stale: false, error: undefined }
  if (state.key === key && state.error) return { rows: undefined, loading: false, stale: false, error: state.error }
  const previous = state.key !== null && state.key !== key ? (results.get(state.key) ?? state.rows) : undefined
  return { rows: previous, loading: true, stale: previous !== undefined, error: undefined }
}
