// @vitest-environment node
// The shared ranking SQL, run in DuckDB-WASM (Node build) on the same synthetic fixture that
// etl/tests/test_queries.py runs in Python duckdb. Expected values: testdata/fixture.sql's header.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { DuckDBBindings, DuckDBConnection } from '@duckdb/duckdb-wasm/blocking'
import { toRows, type Row } from '../db/rows'
import engine from './engine.json'
import pkg from '../../package.json'
import {
  cpiFactor,
  filmRankTimeline,
  leaderboard,
  MEASURES,
  personRank,
  personTotals,
  weekendChart,
  type Query,
} from './index'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)

let db: DuckDBBindings
let conn: DuckDBConnection

beforeAll(async () => {
  const duckdb = await import('@duckdb/duckdb-wasm/blocking')
  const dist = path.dirname(require.resolve('@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs'))
  const bundles = {
    mvp: { mainModule: path.join(dist, 'duckdb-mvp.wasm'), mainWorker: path.join(dist, 'duckdb-node-mvp.worker.cjs') },
    eh: { mainModule: path.join(dist, 'duckdb-eh.wasm'), mainWorker: path.join(dist, 'duckdb-node-eh.worker.cjs') },
  }
  db = await duckdb.createDuckDB(bundles, new duckdb.VoidLogger(), duckdb.NODE_RUNTIME)
  await db.instantiate(() => {})
  conn = db.connect()
  conn.query(readFileSync(path.join(here, 'testdata', 'fixture.sql'), 'utf8'))
}, 60_000)

afterAll(() => {
  conn?.close()
})

function run(q: Query): Row[] {
  const stmt = conn.prepare(q.sql)
  try {
    return toRows(stmt.query(...q.params))
  } finally {
    stmt.close()
  }
}

const pick = (rows: Row[], ...keys: string[]) => rows.map((r) => keys.map((k) => r[k]))

describe('engine', () => {
  it('is the version engine.json pins, for the duckdb-wasm package.json pins', () => {
    expect(pkg.dependencies['@duckdb/duckdb-wasm']).toBe(engine['duckdb-wasm'])
    expect(toRows(conn.query('SELECT version() AS v'))[0]?.v).toBe(engine.engine)
  })
})

describe('leaderboard', () => {
  it('ranks each title by its latest total on or before the date', () => {
    expect(pick(run(leaderboard({ asOf: '1995-06-04', measure: 'nominal' })), 'title_id', 'rank', 'value')).toEqual([
      ['test_delta', 1, 1000],
      ['test_bravo', 2, 400],
      ['test_alpha', 3, 300],
      ['test_charlie', 3, 300],
      ['test_echo', 5, 250],
      ['test_foxtrot', 6, 120],
    ])
    // foxtrot's latest row is unpriced, so it has no CPI value from then on (arg_max_null, not arg_max)
    expect(run(leaderboard({ asOf: '1993-01-10', measure: 'cpi', titleId: 'test_foxtrot' }))).toEqual([])
    expect(run(leaderboard({ asOf: '1981-12-31', measure: 'nominal' }))).toEqual([])
  })

  it('filters, pages and keeps all-time ranks', () => {
    expect(pick(run(leaderboard({ asOf: '1995-06-04', measure: 'nominal', fromYear: 1991 })), 'title_id', 'rank', 'all_time_rank')).toEqual([
      ['test_delta', 1, 1],
      ['test_bravo', 2, 2],
      ['test_charlie', 3, 3],
      ['test_foxtrot', 4, 6],
    ])
    const one = run(leaderboard({ asOf: '1991-01-13', measure: 'nominal', titleId: 'test_charlie' }))
    expect(pick(one, 'rank', 'all_time_rank', 'matching', 'last_change')).toEqual([[1, 2, 1, '1991-01-13']])
    const page = run(leaderboard({ asOf: '1995-06-04', measure: 'nominal', limit: 2, offset: 2 }))
    expect(pick(page, 'title_id', 'matching')).toEqual([
      ['test_alpha', 6],
      ['test_charlie', 6],
    ])
  })

  it('keeps the baseline flags and rejects an unknown measure', () => {
    const echo = run(leaderboard({ asOf: '1995-06-04', measure: 'admissions' }))[1]
    expect([echo?.title_id, echo?.value, echo?.baseline, echo?.baseline_is_rental]).toEqual(['test_echo', 200, true, true])
    expect(() => run(leaderboard({ asOf: '1995-06-04', measure: 'gross' as never }))).toThrow(/unknown measure/)
  })
})

describe('film_rank_timeline', () => {
  it('steps wherever the rank or the value changes', () => {
    expect(pick(run(filmRankTimeline({ titleId: 'test_alpha', measure: 'nominal' })), 'as_of', 'rank', 'value')).toEqual([
      ['1990-01-07', 2, 100],
      ['1990-01-14', 1, 300],
      ['1991-01-13', 2, 300],
      ['1995-06-04', 3, 300],
    ])
    expect(pick(run(filmRankTimeline({ titleId: 'test_foxtrot', measure: 'cpi' })), 'as_of', 'rank', 'value')).toEqual([
      ['1993-01-03', 5, 90],
      ['1993-01-10', null, null],
    ])
  })

  it('agrees with the leaderboard on every date, in every measure', () => {
    const days = toRows(conn.query('SELECT DISTINCT as_of FROM title_cume ORDER BY 1')).map((r) => String(r.as_of))
    for (const measure of MEASURES) {
      for (const titleId of ['test_alpha', 'test_bravo', 'test_charlie', 'test_delta', 'test_echo', 'test_foxtrot']) {
        const steps = run(filmRankTimeline({ titleId, measure }))
        for (const day of days) {
          const board = run(leaderboard({ asOf: day, measure, titleId }))[0]
          const step = steps.filter((s) => String(s.as_of) <= day).at(-1)
          expect(step?.rank ?? null, `${titleId} ${measure} ${day}`).toBe(board?.all_time_rank ?? null)
        }
      }
    }
  })
})

describe('person_totals', () => {
  it('sums every director and the top-billed actors', () => {
    expect(pick(run(personTotals({ asOf: '1995-06-04', role: 'director', measure: 'nominal' })), 'person_id', 'rank', 'value', 'titles')).toEqual([
      ['P1', 1, 1600, 3],
      ['P2', 2, 1400, 2],
      ['P3', 3, 250, 1],
    ])
    expect(pick(run(personTotals({ asOf: '1995-06-04', role: 'actor', measure: 'nominal' })), 'person_id', 'value')).toEqual([
      ['P10', 1300],
      ['P11', 700],
      ['P12', 550],
    ])
    expect(run(personTotals({ asOf: '1995-06-04', role: 'actor', measure: 'nominal', topBilled: 5 }))[0]?.value).toBe(1700)
  })

  it('gives one person their rank among all peers', () => {
    const r = run(personRank({ personId: 'P12', asOf: '1995-06-04', role: 'actor', measure: 'nominal' }))
    expect(pick(r, 'rank', 'value', 'titles', 'peers', 'name')).toEqual([[3, 550, 2, 3, 'Test Actor Twelve']])
  })
})

describe('weekend_chart and cpi_factor', () => {
  it('snaps to the weekend before and shows last week’s rank', () => {
    expect(pick(run(weekendChart({ onDate: '1991-01-16' })), 'weekend_end', 'title_id', 'rank', 'last_rank')).toEqual([
      ['1991-01-13', 'test_charlie', 1, 2],
      ['1991-01-13', 'test_bravo', 2, 1],
    ])
    expect(run(weekendChart({ onDate: '1989-12-31' }))).toEqual([])
  })

  it('converts 1982-84 dollars to a month’s dollars', () => {
    expect(pick(run(cpiFactor({ onDate: '2000-01-01' })), 'month', 'factor', 'is_interpolated')).toEqual([['1995-06-01', 1.525, true]])
  })
})
