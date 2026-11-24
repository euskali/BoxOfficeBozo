import { Link, useParams } from 'react-router'
import { FilmLink, num, str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import { BaselineMark, FlagLegend } from '../components/Flags'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import SectionBar from '../components/SectionBar'
import TableBox from '../components/TableBox'
import ViewControls, { ControlsSlot } from '../components/ViewControls'
import type { Row } from '../db/rows'
import { useQuery } from '../db/useQuery'
import { count, longDay, MEASURE_LONG, MEASURE_NAMES, measureValue, ordinal } from '../lib/format'
import { useAsOf, useCpiDollars, useView } from '../lib/view'
import { filmography, person, personRank, TOP_BILLED, type Role } from '../queries'

const ROLE_PLURAL: Record<Role, string> = { director: 'directors', actor: 'actors' }

function CareerRow({ role, row, loading, asOf, measure, factor, peopleLink }: {
  role: Role
  row: Row | undefined
  loading: boolean
  asOf: string
  measure: 'nominal' | 'cpi' | 'admissions'
  factor: number | null
  peopleLink: string
}) {
  return (
    <tr>
      <th scope="row">{role === 'director' ? 'Director' : `Actor (top ${TOP_BILLED} billed)`}</th>
      <td className="num">{loading ? '…' : row ? num(row.titles) : 0}</td>
      <td className="num">{loading ? '…' : row ? measureValue(measure, num(row.value), factor) : '–'}</td>
      <td>
        {loading ? (
          '…'
        ) : row ? (
          <>
            <b>{ordinal(num(row.rank) ?? 0)}</b> of {count(num(row.peers) ?? 0)} {ROLE_PLURAL[role]} on {longDay(asOf)}{' '}
            <Link to={peopleLink}>(list)</Link>
          </>
        ) : (
          'not ranked yet'
        )}
      </td>
    </tr>
  )
}

export default function Person() {
  const { personId = '' } = useParams()
  const { measure, cpiBasis, link } = useView()
  const { asOf, latest, error: latestError } = useAsOf()
  const cpi = useCpiDollars(cpiBasis, asOf)
  const personQ = useQuery(person({ personId }))
  const p = personQ.rows?.[0]
  const directed = num(p?.directed) ?? 0
  const acted = num(p?.acted) ?? 0
  const asDirector = useQuery(asOf && directed ? personRank({ personId, asOf, role: 'director', measure }) : null)
  const asActor = useQuery(asOf && acted ? personRank({ personId, asOf, role: 'actor', measure }) : null)
  const films = useQuery(asOf && p ? filmography({ personId, asOf, measure }) : null)
  const error = personQ.error ?? latestError ?? asDirector.error ?? asActor.error ?? films.error
  const name = p ? String(p.name ?? personId) : null
  const notFound = personQ.rows !== undefined && !p
  const imdb = str(p?.imdb_id)
  const roles: Role[] = [...(directed ? (['director'] as const) : []), ...(acted ? (['actor'] as const) : [])]
  const peopleLink = (role: Role) => `/people${link({ role })}`

  return (
    <>
      <PageHead
        section="Person"
        crumbs={[{ label: 'People', to: '/people' }, { label: name ?? personId }]}
        title={name ?? (notFound ? 'Person not found' : 'Person')}
        docTitle={name}
      >
        <p>
          Career box office as of the date you pick: the total of every film this person directed, or
          was billed in the top {TOP_BILLED} of, and where that total ranked among all directors or
          actors in our charts on that day. Credits and billing order come from Wikidata.
        </p>
      </PageHead>

      {error && <ErrorBox error={error} />}
      {notFound && (
        <p>
          We have no one with the ID <code>{personId}</code>. Try the search box.
        </p>
      )}
      {!p && !notFound && !error && <LoadingBox what="this person" minHeight={300} />}

      {p && (
        <>
          <p className="text-small">
            <a href={`https://www.wikidata.org/wiki/${personId}`}>Wikidata {personId}</a>
            {imdb && (
              <>
                {' · '}
                <a href={`https://www.imdb.com/name/${imdb}/`}>IMDb {imdb}</a>
              </>
            )}
            {' · '}
            {[directed ? `directed ${directed} film${directed === 1 ? '' : 's'}` : null, acted ? `credited in the cast of ${acted}` : null]
              .filter(Boolean)
              .join(', ')}
          </p>

          {asOf && latest ? <ViewControls asOf={asOf} latest={latest} cpi={cpi} /> : <ControlsSlot />}

          {roles.length > 0 && (
            <>
              <h2 className="sub-bar">Career totals{asOf ? ` on ${longDay(asOf)}` : ''}</h2>
              <TableBox label="Career totals">
                <table className="grid-table w-full">
                  <caption className="sr-only">Career totals by {MEASURE_LONG[measure]}</caption>
                  <thead>
                    <tr>
                      <th scope="col">As</th>
                      <th scope="col" className="num">
                        Films
                      </th>
                      <th scope="col" className="num">
                        {MEASURE_NAMES[measure]}
                        {measure === 'cpi' ? ` (${cpi.label})` : ''}
                      </th>
                      <th scope="col">Rank</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roles.map((role) => {
                      const q = role === 'director' ? asDirector : asActor
                      return (
                        <CareerRow
                          key={role}
                          role={role}
                          row={q.rows?.[0]}
                          loading={!q.rows || !asOf}
                          asOf={asOf ?? ''}
                          measure={measure}
                          factor={cpi.factor}
                          peopleLink={peopleLink(role)}
                        />
                      )
                    })}
                  </tbody>
                </table>
              </TableBox>
            </>
          )}

          <SectionBar>Filmography</SectionBar>
          {films.rows ? (
            <>
              <TableBox label="Filmography">
                <table className="grid-table w-full">
                  <caption className="sr-only">
                    Films, with each film&rsquo;s total and all-time rank on {asOf ? longDay(asOf) : 'the date'}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="num">
                        Year
                      </th>
                      <th scope="col">Title</th>
                      <th scope="col">Credit</th>
                      <th scope="col" className="num">
                        {MEASURE_NAMES[measure]}
                      </th>
                      <th scope="col" className="num">
                        All-time rank
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {films.rows.map((r) => (
                      <tr key={`${String(r.title_id)}:${String(r.role)}`} className={r.counted ? undefined : 'uncounted'}>
                        <td className="num">{num(r.year)}</td>
                        <th scope="row">
                          <FilmLink id={r.title_id} title={r.title} />
                          <BaselineMark baseline={r.baseline} rental={r.baseline_is_rental} />
                        </th>
                        <td>
                          {r.role === 'director' ? 'Director' : `Actor${num(r.billing) ? `, billed ${ordinal(num(r.billing)!)}` : ''}`}
                          {!r.counted && <span className="text-muted"> (not counted)</span>}
                        </td>
                        <td className="num">{num(r.value) === null ? '–' : measureValue(measure, num(r.value), cpi.factor)}</td>
                        <td className="num">{num(r.all_time_rank) ?? '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableBox>
              <FlagLegend
                baseline={films.rows.some((r) => r.baseline === true && r.baseline_is_rental !== true)}
                rental={films.rows.some((r) => r.baseline === true && r.baseline_is_rental === true)}
              />
              <p className="text-small">
                &ldquo;Not counted&rdquo;: an acting credit billed below {ordinal(TOP_BILLED)}, or with no billing
                position, isn&rsquo;t added to the career total. A dash means the film had no total yet on that
                date.
              </p>
            </>
          ) : (
            !error && <LoadingBox what="the filmography" minHeight={240} />
          )}
        </>
      )}
    </>
  )
}
