import { useSearchParams } from 'react-router'
import { useQuery } from '../db/useQuery'
import { cpiFactor, latestDate, MEASURES, type Day, type Measure } from '../queries'
import { clampDay, FIRST_DAY, parseDay, today } from './dates'
import { monthLabel } from './format'

export type CpiBasis = 'today' | 'then'

/**
 * The view state every ranking page keeps in its URL, so any view can be shared:
 *   ?date=YYYY-MM-DD   the date to rank on (absent: the latest weekend in the data)
 *   &m=nominal|cpi|admissions
 *   &cpi=then          CPI-adjusted dollars of the chosen date instead of today's
 */
export function useView() {
  const [params] = useSearchParams()
  const date = parseDay(params.get('date'))
  const m = params.get('m')
  const measure: Measure = MEASURES.includes(m as Measure) ? (m as Measure) : 'nominal'
  const cpiBasis: CpiBasis = params.get('cpi') === 'then' ? 'then' : 'today'

  /** A query string with some parameters changed (null removes one), for links. */
  function link(changes: Record<string, string | number | null>): string {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, String(v))
    }
    if (next.get('m') === 'nominal') next.delete('m')
    if (next.get('cpi') === 'today') next.delete('cpi')
    const s = next.toString()
    return s ? `?${s}` : '?'
  }

  return { params, date, measure, cpiBasis, link }
}

/** The newest date the data covers (latest_date.sql), once loaded. */
export function useLatestDate(): { latest: Day | undefined; error: Error | undefined } {
  const q = useQuery(latestDate())
  const v = q.rows?.[0]?.as_of
  return { latest: typeof v === 'string' ? v : undefined, error: q.error }
}

/**
 * The date a page ranks on: the URL's (kept within the data's range) or the latest weekend.
 * Undefined until the latest date is known.
 */
export function useAsOf(): { asOf: Day | undefined; latest: Day | undefined; error: Error | undefined } {
  const { date } = useView()
  const { latest, error } = useLatestDate()
  if (!latest) return { asOf: undefined, latest, error }
  return { asOf: date ? clampDay(date, FIRST_DAY, latest) : latest, latest, error }
}

export interface CpiDollars {
  /** Multiply a cume_cpi value by this for dollars of `month`. */
  factor: number | null
  /** 'YYYY-MM-01' of the CPI month used. */
  month: string | null
  interpolated: boolean
  /** "Oct 2026 dollars". */
  label: string
}

/** The CPI factor for the view: today's dollars (the latest CPI month) or the chosen date's. */
export function useCpiDollars(basis: CpiBasis, asOf: Day | undefined, enabled = true): CpiDollars {
  const onDate = basis === 'then' ? asOf : today()
  const q = useQuery(enabled && onDate ? cpiFactor({ onDate }) : null)
  const row = q.rows?.[0]
  const month = typeof row?.month === 'string' ? row.month : null
  return {
    factor: typeof row?.factor === 'number' ? row.factor : null,
    month,
    interpolated: row?.is_interpolated === true,
    label: month ? `${monthLabel(month)} dollars` : 'adjusted dollars',
  }
}
