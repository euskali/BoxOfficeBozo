import type { Day } from '../queries'

/** The first date the rankings cover: pre-1982 baselines are dated 1 Jan 1982. */
export const FIRST_DAY: Day = '1982-01-01'

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/

/** A valid 'YYYY-MM-DD' string, or null. */
export function parseDay(s: string | null | undefined): Day | null {
  if (!s) return null
  const m = DAY_RE.exec(s)
  if (!m) return null
  const d = new Date(`${s}T00:00:00Z`)
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== s) return null
  return s
}

function toDay(d: Date): Day {
  return d.toISOString().slice(0, 10)
}

export function addDays(day: Day, n: number): Day {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return toDay(d)
}

/** The same day n years on (or back); 29 Feb becomes 28 Feb in a non-leap year. */
export function addYears(day: Day, n: number): Day {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number]
  const target = new Date(Date.UTC(y + n, m - 1, 1))
  const lastOfMonth = new Date(Date.UTC(y + n, m, 0)).getUTCDate()
  target.setUTCDate(Math.min(d, lastOfMonth))
  return toDay(target)
}

/** The Sunday on or before a day (charts end on Sundays, holiday charts aside). */
export function sundayOnOrBefore(day: Day): Day {
  const d = new Date(`${day}T00:00:00Z`)
  return addDays(day, -d.getUTCDay())
}

export function clampDay(day: Day, min: Day, max: Day): Day {
  return day < min ? min : day > max ? max : day
}

/** Today's date (UTC) as 'YYYY-MM-DD'. */
export function today(): Day {
  return toDay(new Date())
}
