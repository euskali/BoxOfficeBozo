import { Link } from 'react-router'
import type { Row } from '../db/rows'
import { MEASURE_NAMES } from '../lib/format'
import type { Measure } from '../queries'

/** A film link: "Titanic" (the year goes in its own column or after it). */
export function FilmLink({ id, title }: { id: unknown; title: unknown }) {
  return <Link to={`/film/${encodeURIComponent(String(id))}`}>{String(title ?? id)}</Link>
}

export function PersonLink({ id, name }: { id: unknown; name: unknown }) {
  return <Link to={`/person/${encodeURIComponent(String(id))}`}>{String(name ?? id)}</Link>
}

/**
 * A column header that sorts the list by a measure: the current one shows ▼ and aria-sort, the
 * others link to it.
 */
export function MeasureHeader({
  m,
  current,
  href,
  label,
}: {
  m: Measure
  current: Measure
  href: string
  label?: string
}) {
  const text = label ?? MEASURE_NAMES[m]
  return (
    <th scope="col" className="num" aria-sort={m === current ? 'descending' : undefined}>
      {m === current ? (
        <>
          {text} <span aria-hidden="true">▼</span>
        </>
      ) : (
        <Link to={href} className="th-link">
          {text}
        </Link>
      )}
    </th>
  )
}

export const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)
export const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)

/** True when any row has a baseline flag (of the given kind), for the table's legend. */
export function hasBaseline(rows: Row[], rental: boolean): boolean {
  return rows.some((r) => r.baseline === true && (r.baseline_is_rental === true) === rental)
}
