import { Fragment } from 'react'
import { Link } from 'react-router'
import { num, PersonLink } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import Pager from '../components/Pager'
import TableBox from '../components/TableBox'
import ViewControls, { ControlsSlot } from '../components/ViewControls'
import { useQuery } from '../db/useQuery'
import { longDay, MEASURE_LONG, MEASURE_NAMES, measureValue } from '../lib/format'
import { useAsOf, useCpiDollars, useView } from '../lib/view'
import { personTotals, TOP_BILLED, type Role } from '../queries'

const PAGE_SIZE = 100
const ROLES: { role: Role; label: string }[] = [
  { role: 'director', label: 'Directors' },
  { role: 'actor', label: 'Actors' },
]

export default function People() {
  const { params, measure, cpiBasis, link } = useView()
  const role: Role = params.get('role') === 'actor' ? 'actor' : 'director'
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1)
  const { asOf, latest, error: latestError } = useAsOf()
  const cpi = useCpiDollars(cpiBasis, asOf)
  const q = useQuery(asOf ? personTotals({ asOf, role, measure, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }) : null)
  const rows = q.rows
  const error = q.error ?? latestError
  const total = num(rows?.[0]?.peers) ?? 0
  const label = role === 'director' ? 'directors' : 'actors'

  return (
    <>
      <PageHead section="People" crumbs={[{ label: 'People' }]} title="Top directors and actors, as of any date">
        <p>
          Career box office for every director and actor in our charts, as it stood on the date you
          pick. A director&rsquo;s total adds up every film they directed; an actor&rsquo;s adds up the films
          they were billed in the top {TOP_BILLED} of, by Wikidata&rsquo;s cast order. Use the search box to find
          anyone.
        </p>
      </PageHead>

      {!(asOf && latest) && !error && <ControlsSlot height={128} />}
      {asOf && latest && (
        <ViewControls asOf={asOf} latest={latest} cpi={cpi}>
          <nav aria-label="Role" className="mt-1">
            <span className="font-bold">Show:</span>{' '}
            {ROLES.map((r, i) => (
              <Fragment key={r.role}>
                {i > 0 && <span aria-hidden="true"> | </span>}
                {r.role === role ? (
                  <b aria-current="true" className="current-choice">
                    {r.label}
                  </b>
                ) : (
                  <Link to={link({ role: r.role === 'director' ? null : r.role, page: null })}>{r.label}</Link>
                )}
              </Fragment>
            ))}
          </nav>
        </ViewControls>
      )}

      {error && <ErrorBox error={error} />}
      {!rows && !error && <LoadingBox what={`the top ${label}`} minHeight={600} />}

      {rows && asOf && (
        <>
          <h2 className="sub-bar">
            Top {label} by {MEASURE_LONG[measure]}, as of {longDay(asOf)}
            {q.stale && <span className="font-normal"> (updating…)</span>}
          </h2>
          {rows.length === 0 ? (
            <p>No {label} have a total on this date.</p>
          ) : (
            <>
              <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
              <TableBox label={`Top ${label}`}>
                <table className="grid-table w-full">
                  <caption className="sr-only">
                    Top {label} as of {longDay(asOf)}, by {MEASURE_LONG[measure]}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="num">
                        Rank
                      </th>
                      <th scope="col">Name</th>
                      <th scope="col" className="num">
                        Films
                      </th>
                      <th scope="col" className="num">
                        {MEASURE_NAMES[measure]}
                        {measure === 'cpi' ? ` (${cpi.label})` : ''}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={String(r.person_id)}>
                        <td className="num">{num(r.rank)}</td>
                        <th scope="row">
                          <PersonLink id={r.person_id} name={r.name} />
                        </th>
                        <td className="num">{num(r.titles)}</td>
                        <td className="num">{measureValue(measure, num(r.value), cpi.factor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableBox>
              <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
            </>
          )}
        </>
      )}
    </>
  )
}
