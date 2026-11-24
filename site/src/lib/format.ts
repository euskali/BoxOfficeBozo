import type { Measure } from '../queries'
import { formatRetroDate } from './formatRetroDate'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const

/** "$1,234,567" (whole dollars). */
export function money(n: number): string {
  return `$${Math.round(n).toLocaleString('en-US')}`
}

/** "1,234,567" (whole numbers). */
export function count(n: number): string {
  return Math.round(n).toLocaleString('en-US')
}

/** 'YYYY-MM-DD' as a UTC Date. */
export function dayToDate(day: string): Date {
  return new Date(`${day}T00:00:00Z`)
}

/** "Sun Apr 5 1998". */
export function longDay(day: string): string {
  return formatRetroDate(dayToDate(day))
}

/** "Apr 5 1998". */
export function shortDay(day: string): string {
  const d = dayToDate(day)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()} ${d.getUTCFullYear()}`
}

/** "Oct 2026" for a month's first day. */
export function monthLabel(day: string): string {
  const d = dayToDate(day)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`
}

/** Percent change from `before` to `after`, as "-24.2%" or "+3.0%"; null when it can't be computed. */
export function pctChange(after: number | null, before: number | null): string | null {
  if (after === null || before === null || before <= 0) return null
  const p = ((after - before) / before) * 100
  return `${p > 0 ? '+' : ''}${p.toFixed(1)}%`
}

export const MEASURE_NAMES: Record<Measure, string> = {
  nominal: 'Nominal $',
  cpi: 'CPI-adjusted $',
  admissions: 'Est. tickets',
}

export const MEASURE_LONG: Record<Measure, string> = {
  nominal: 'box office gross in the dollars of the day',
  cpi: 'box office gross adjusted for inflation (CPI-U)',
  admissions: 'estimated tickets sold',
}

/**
 * A measure's value for display. cume_cpi values are in 1982-84 dollars; `cpiFactor` converts
 * them (cpi_factor.sql). Admissions are whole tickets.
 */
export function measureValue(measure: Measure, value: number | null, cpiFactor: number | null): string {
  if (value === null) return '–'
  if (measure === 'admissions') return count(value)
  if (measure === 'cpi') return cpiFactor === null ? '…' : money(value * cpiFactor)
  return money(value)
}

/** "1st", "2nd", "3rd", "4th"... */
export function ordinal(n: number): string {
  const s = n % 100
  if (s >= 11 && s <= 13) return `${n}th`
  const last = n % 10
  return `${n}${last === 1 ? 'st' : last === 2 ? 'nd' : last === 3 ? 'rd' : 'th'}`
}
