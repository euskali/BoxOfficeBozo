// The site's SQL lives in plain .sql files so the browser (DuckDB-WASM) and the Python tests
// (etl/boffo_etl/queries.py) run the same text. Parameters are positional ($1, $2, ...), in the
// order each file's header documents; these builders and the Python wrappers keep that order.
import browseFilmsSql from './browse_films.sql?raw'
import cpiFactorSql from './cpi_factor.sql?raw'
import filmCreditsSql from './film_credits.sql?raw'
import filmRankTimelineSql from './film_rank_timeline.sql?raw'
import filmReleasesSql from './film_releases.sql?raw'
import filmSql from './film.sql?raw'
import filmWeekendsSql from './film_weekends.sql?raw'
import filmographySql from './filmography.sql?raw'
import latestDateSql from './latest_date.sql?raw'
import leaderboardSql from './leaderboard.sql?raw'
import personSql from './person.sql?raw'
import personTotalsSql from './person_totals.sql?raw'
import searchIndexSql from './search_index.sql?raw'
import searchSql from './search.sql?raw'
import weekendChartSql from './weekend_chart.sql?raw'

export type Measure = 'nominal' | 'cpi' | 'admissions'
export type Role = 'director' | 'actor'
export type Param = string | number | null

/** The Parquet tables the site loads (public/data/<name>.parquet), under these names. */
export const TABLES = ['titles', 'releases', 'snapshots', 'title_cume', 'credits', 'people', 'cpi'] as const
export type TableName = (typeof TABLES)[number]

/** Tables built in the browser from loaded ones, by running a .sql file once. */
export const DERIVED = {
  search_index: { sql: searchIndexSql, from: ['titles', 'title_cume', 'people', 'credits'] as TableName[] },
} as const
export type DerivedName = keyof typeof DERIVED

export interface Query {
  name: string
  sql: string
  params: Param[]
  /** What the query reads, so the site loads only those tables first. */
  tables: readonly (TableName | DerivedName)[]
}

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
  compareTo?: Day | null
}): Query {
  return {
    name: 'leaderboard',
    sql: leaderboardSql,
    params: [
      o.asOf,
      o.measure,
      o.limit ?? 100,
      o.offset ?? 0,
      o.fromYear ?? null,
      o.toYear ?? null,
      o.titleId ?? null,
      o.compareTo ?? null,
    ],
    tables: ['title_cume', 'titles'],
  }
}

export function latestDate(): Query {
  return { name: 'latest_date', sql: latestDateSql, params: [], tables: ['title_cume'] }
}

export function filmRankTimeline(o: { titleId: string; measure: Measure }): Query {
  return {
    name: 'film_rank_timeline',
    sql: filmRankTimelineSql,
    params: [o.titleId, o.measure],
    tables: ['title_cume'],
  }
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
    tables: ['title_cume', 'titles', 'credits', 'people'],
  }
}

/** One person's rank and career total among everyone in that role (person_totals.sql, filtered). */
export function personRank(o: { personId: string; asOf: Day; role: Role; measure: Measure; topBilled?: number }): Query {
  return personTotals({ ...o, limit: 1, offset: 0 })
}

export function weekendChart(o: { onDate: Day }): Query {
  return {
    name: 'weekend_chart',
    sql: weekendChartSql,
    params: [o.onDate],
    tables: ['snapshots', 'releases', 'titles'],
  }
}

/** Multiply a cume_cpi value (1982-84 dollars) by the result's factor for dollars of onDate's month. */
export function cpiFactor(o: { onDate: Day }): Query {
  return { name: 'cpi_factor', sql: cpiFactorSql, params: [o.onDate], tables: ['cpi'] }
}

export function film(o: { titleId: string }): Query {
  return { name: 'film', sql: filmSql, params: [o.titleId], tables: ['titles', 'title_cume', 'releases'] }
}

export function filmCredits(o: { titleId: string }): Query {
  return { name: 'film_credits', sql: filmCreditsSql, params: [o.titleId], tables: ['credits', 'people'] }
}

export function filmReleases(o: { titleId: string }): Query {
  return { name: 'film_releases', sql: filmReleasesSql, params: [o.titleId], tables: ['releases', 'snapshots'] }
}

export function filmWeekends(o: { titleId: string }): Query {
  return { name: 'film_weekends', sql: filmWeekendsSql, params: [o.titleId], tables: ['snapshots', 'releases'] }
}

export function person(o: { personId: string }): Query {
  return { name: 'person', sql: personSql, params: [o.personId], tables: ['people', 'credits'] }
}

export function filmography(o: { personId: string; asOf: Day; measure: Measure; topBilled?: number }): Query {
  return {
    name: 'filmography',
    sql: filmographySql,
    params: [o.personId, o.asOf, o.measure, o.topBilled ?? TOP_BILLED],
    tables: ['credits', 'titles', 'title_cume'],
  }
}

export function browseFilms(o: { letter: string; limit?: number; offset?: number }): Query {
  return {
    name: 'browse_films',
    sql: browseFilmsSql,
    params: [o.letter, o.limit ?? 100, o.offset ?? 0],
    tables: ['titles', 'title_cume'],
  }
}

export function search(o: { text: string; limit?: number }): Query {
  return { name: 'search', sql: searchSql, params: [o.text, o.limit ?? 8], tables: ['search_index'] }
}
