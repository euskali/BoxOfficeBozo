// The ranking SQL lives in plain .sql files so the browser (DuckDB-WASM) and the Python tests
// (etl/boffo_etl/queries.py) run the same text. Parameters are positional ($1, $2, ...), in the
// order each file's header documents; these builders and the Python wrappers keep that order.
import cpiFactorSql from './cpi_factor.sql?raw'
import filmRankTimelineSql from './film_rank_timeline.sql?raw'
import leaderboardSql from './leaderboard.sql?raw'
import personTotalsSql from './person_totals.sql?raw'
import weekendChartSql from './weekend_chart.sql?raw'

export type Measure = 'nominal' | 'cpi' | 'admissions'
export type Role = 'director' | 'actor'
export type Param = string | number | null

export interface Query {
  name: string
  sql: string
  params: Param[]
}

/** The Parquet tables the queries read, loaded under these names. */
export const TABLES = ['titles', 'releases', 'snapshots', 'title_cume', 'credits', 'people', 'cpi'] as const
export const MEASURES: readonly Measure[] = ['nominal', 'cpi', 'admissions']
/** The default actor rollup rule: films an actor is billed in the top 4 of. */
export const TOP_BILLED = 4

/** A date as the queries take it: 'YYYY-MM-DD'. */
export type Day = string

export function leaderboard(o: {
  asOf: Day
  measure: Measure
  limit?: number
  offset?: number
  fromYear?: number | null
  toYear?: number | null
  titleId?: string | null
}): Query {
  return {
    name: 'leaderboard',
    sql: leaderboardSql,
    params: [o.asOf, o.measure, o.limit ?? 100, o.offset ?? 0, o.fromYear ?? null, o.toYear ?? null, o.titleId ?? null],
  }
}

export function filmRankTimeline(o: { titleId: string; measure: Measure }): Query {
  return { name: 'film_rank_timeline', sql: filmRankTimelineSql, params: [o.titleId, o.measure] }
}

export function personTotals(o: {
  asOf: Day
  role: Role
  measure: Measure
  topBilled?: number
  limit?: number
  offset?: number
  personId?: string | null
}): Query {
  return {
    name: 'person_totals',
    sql: personTotalsSql,
    params: [o.asOf, o.role, o.measure, o.topBilled ?? TOP_BILLED, o.limit ?? 100, o.offset ?? 0, o.personId ?? null],
  }
}

/** One person's rank and career total among everyone in that role (person_totals.sql, filtered). */
export function personRank(o: { personId: string; asOf: Day; role: Role; measure: Measure; topBilled?: number }): Query {
  return personTotals({ ...o, limit: 1, offset: 0 })
}

export function weekendChart(o: { onDate: Day }): Query {
  return { name: 'weekend_chart', sql: weekendChartSql, params: [o.onDate] }
}

/** Multiply a cume_cpi value (1982-84 dollars) by the result's factor for dollars of onDate's month. */
export function cpiFactor(o: { onDate: Day }): Query {
  return { name: 'cpi_factor', sql: cpiFactorSql, params: [o.onDate] }
}
