// @vitest-environment node
// The shared site SQL, run in DuckDB-WASM (Node build) on the same synthetic fixture that
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
  browseFilms,
  cpiFactor,
  DERIVED,
  film,
  filmCredits,
  filmography,
  filmRankTimeline,
  filmReleases,
  filmWeekends,
  latestDate,
  leaderboard,
  MEASURES,
  person,
  personRank,
  personTotals,
  search,
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

  it('gives last week’s gross and the charts either side', () => {
    const rows = run(weekendChart({ onDate: '1991-01-16' }))
    expect(pick(rows, 'title_id', 'weekend_gross', 'last_weekend_gross', 'prev_weekend_end', 'next_weekend_end')).toEqual([
      ['test_charlie', 250, 50, '1991-01-06', '1995-06-04'],
      ['test_bravo', 200, 200, '1991-01-06', '1995-06-04'],
    ])
    expect(pick(run(weekendChart({ onDate: '1995-06-04' })), 'last_rank', 'last_weekend_gross', 'prev_weekend_end', 'next_weekend_end')).toEqual([
      [null, null, '1991-01-13', null],
    ])
  })
})

describe('leaderboard compared with an earlier date', () => {
  it('ranks the earlier date within the same year filters', () => {
    expect(pick(run(leaderboard({ asOf: '1995-06-04', measure: 'nominal', compareTo: '1991-01-13' })), 'title_id', 'rank', 'prev_rank')).toEqual([
      ['test_delta', 1, null],
      ['test_bravo', 2, 1],
      ['test_alpha', 3, 2],
      ['test_charlie', 3, 2],
      ['test_echo', 5, 4],
      ['test_foxtrot', 6, null],
    ])
    expect(
      pick(run(leaderboard({ asOf: '1995-06-04', measure: 'nominal', fromYear: 1991, compareTo: '1991-01-13' })), 'title_id', 'prev_rank'),
    ).toEqual([
      ['test_delta', null],
      ['test_bravo', 1],
      ['test_charlie', 2],
      ['test_foxtrot', null],
    ])
    expect(run(latestDate())).toEqual([{ as_of: '1995-06-04' }])
  })
})

describe('film pages', () => {
  it('gives the titles row with its latest totals', () => {
    const alpha = run(film({ titleId: 'test_alpha' }))
    expect(pick(alpha, 'title', 'year', 'release_date', 'distributor', 'first_as_of', 'last_as_of', 'cume_nominal', 'cume_cpi', 'cume_admissions', 'releases', 'weekends')).toEqual([
      ['Test Film Alpha', 1990, '1990-01-05', 'Fictional Pictures', '1990-01-07', '1990-01-14', 300, 450, 150, 1, 2],
    ])
    expect(pick(run(film({ titleId: 'test_foxtrot' })), 'cume_nominal', 'cume_cpi', 'cume_admissions', 'releases')).toEqual([[120, null, null, null]])
    expect(pick(run(film({ titleId: 'test_echo' })), 'baseline', 'baseline_is_rental', 'pre1982_baseline_gross')).toEqual([[true, true, 250]])
    expect(pick(run(film({ titleId: 'test_golf' })), 'title', 'cume_nominal')).toEqual([['The Golf Picture', null]])
    expect(run(film({ titleId: 'no_such_title' }))).toEqual([])
  })

  it('lists credits, releases and weekends', () => {
    expect(pick(run(filmCredits({ titleId: 'test_charlie' })), 'role', 'billing', 'person_id')).toEqual([
      ['director', null, 'P1'],
      ['actor', 3, 'P12'],
      ['actor', null, 'P13'],
    ])
    expect(pick(run(filmReleases({ titleId: 'test_delta' })), 'release_id', 'label', 'weekends', 'is_rerelease', 'total_gross')).toEqual([
      ['rel_delta', 'Special Edition', 1, true, 1000],
    ])
    expect(pick(run(filmWeekends({ titleId: 'test_bravo' })), 'weekend_end', 'rank', 'weekend_gross', 'last_weekend_gross', 'total_gross')).toEqual([
      ['1991-01-06', 1, 200, null, 200],
      ['1991-01-13', 2, 200, 200, 400],
    ])
  })
})

describe('person pages', () => {
  it('counts credits by role', () => {
    expect(run(person({ personId: 'P1' }))).toEqual([{ person_id: 'P1', name: 'Test Director One', imdb_id: null, directed: 3, acted: 0 }])
    expect(run(person({ personId: 'P99' }))).toEqual([])
  })

  it('values each film on the date and marks the credits that count', () => {
    const rows = run(filmography({ personId: 'P10', asOf: '1995-06-04', measure: 'nominal' }))
    expect(pick(rows, 'title_id', 'billing', 'counted', 'value', 'all_time_rank')).toEqual([
      ['test_alpha', 1, true, 300, 3],
      ['test_bravo', 5, false, 400, 2],
      ['test_delta', 4, true, 1000, 1],
    ])
    expect(pick(run(filmography({ personId: 'P12', asOf: '1995-06-04', measure: 'cpi' })), 'title_id', 'value', 'all_time_rank', 'baseline', 'baseline_is_rental')).toEqual([
      ['test_echo', 600, 2, true, true],
      ['test_charlie', 270, 5, false, null],
    ])
  })
})

describe('browse and search', () => {
  it('files films by first letter past a leading article', () => {
    expect(pick(run(browseFilms({ letter: 'T', limit: 2, offset: 1 })), 'title_id', 'gross', 'matching')).toEqual([
      ['test_bravo', 400, 6],
      ['test_charlie', 300, 6],
    ])
    expect(pick(run(browseFilms({ letter: 'g' })), 'title')).toEqual([['The Golf Picture']])
    expect(pick(run(browseFilms({ letter: '#' })), 'title_id')).toEqual([['test_hotel']])
  })

  it('finds films and people by word start', () => {
    conn.query(DERIVED.search_index.sql)
    const hits = (text: string, limit?: number) => pick(run(search({ text, limit })), 'kind', 'id', 'match')
    expect(hits('alpha')).toEqual([['film', 'test_alpha', 2]])
    expect(hits('golf picture')).toEqual([['film', 'test_golf', 0]])
    expect(hits('test', 3)).toEqual([
      ['film', 'test_delta', 1],
      ['film', 'test_bravo', 1],
      ['film', 'test_alpha', 1],
      ['person', 'P10', 1],
      ['person', 'P1', 1],
      ['person', 'P11', 1],
    ])
    expect(hits('Test-Film  ALPHA!')).toEqual([['film', 'test_alpha', 0]])
    expect(hits('testdirector')).toEqual([
      ['person', 'P1', 3],
      ['person', 'P2', 3],
      ['person', 'P3', 3],
    ])
    expect(hits('...')).toEqual([])
  })
})
