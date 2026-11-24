import { lazy, Suspense, useMemo, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { FilmLink, num, PersonLink, str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import { BaselineMark, EstimateMark, FlagLegend } from '../components/Flags'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import SectionBar from '../components/SectionBar'
import TableBox from '../components/TableBox'
import ViewControls, { ControlsSlot } from '../components/ViewControls'
import type { Row } from '../db/rows'
import { useQuery } from '../db/useQuery'
import { count, longDay, MEASURE_LONG, MEASURE_NAMES, measureValue, money, ordinal, pctChange, shortDay } from '../lib/format'
import { useAsOf, useCpiDollars, useView } from '../lib/view'
import { film, filmCredits, filmRankTimeline, filmReleases, filmWeekends, leaderboard, type Day } from '../queries'
import { LETTERS } from '../components/LetterBar'

const RankChart = lazy(() => import('../components/RankChart'))

const STARRING = 4 // top-billed actors in the header (the actor rollup rule)

function letterOf(title: string): string {
  const sort = title.replace(/^(The|A|An) /, '').normalize('NFD').replace(/[̀-ͯ]/g, '')
  const c = sort.charAt(0).toUpperCase()
  return (LETTERS as readonly string[]).includes(c) ? c : '#'
}

function Facts({ f, credits, cpiToday }: { f: Row; credits: Row[] | undefined; cpiToday: ReturnType<typeof useCpiDollars> }) {
  const directors = credits?.filter((c) => c.role === 'director') ?? []
  const cast = credits?.filter((c) => c.role === 'actor').slice(0, STARRING) ?? []
  const qid = str(f.wikidata_qid)
  const tt = str(f.title_id)?.startsWith('tt') ? str(f.title_id) : null
  const rows: [string, ReactNode][] = [
    ['Released', str(f.release_date) ? longDay(str(f.release_date)!) : num(f.year)],
    ['Distributor', str(f.distributor) ?? '–'],
    ['Genre', str(f.genres) ?? '–'],
    ['Rating', str(f.mpaa) ?? '–'],
    [
      directors.length === 1 ? 'Director' : 'Directors',
      credits === undefined ? '…' : directors.length ? directors.map((d, i) => <span key={String(d.person_id)}>{i > 0 && ', '}<PersonLink id={d.person_id} name={d.name} /></span>) : '–',
    ],
    [
      'Starring',
      credits === undefined ? '…' : cast.length ? cast.map((d, i) => <span key={String(d.person_id)}>{i > 0 && ', '}<PersonLink id={d.person_id} name={d.name} /></span>) : '–',
    ],
    [
      'Total gross',
      num(f.cume_nominal) === null ? (
        'not charted'
      ) : (
        <>
          {money(num(f.cume_nominal)!)}
          <BaselineMark baseline={f.baseline} rental={f.baseline_is_rental} />
          {str(f.last_as_of) && <span className="text-muted"> through {shortDay(str(f.last_as_of)!)}</span>}
        </>
      ),
    ],
    ['Adjusted for inflation', `${measureValue('cpi', num(f.cume_cpi), cpiToday.factor)} (${cpiToday.label})`],
    ['Est. tickets sold', num(f.cume_admissions) === null ? '–' : count(num(f.cume_admissions)!)],
    [
      'Charted',
      num(f.weekends)
        ? `${num(f.weekends)} weekend${num(f.weekends) === 1 ? '' : 's'}, ${num(f.releases)} release${num(f.releases) === 1 ? '' : 's'}`
        : '–',
    ],
    [
      'Links',
      <>
        {qid ? <a href={`https://www.wikidata.org/wiki/${qid}`}>Wikidata {qid}</a> : 'no Wikidata match'}
        {tt && (
          <>
            {' · '}
            <a href={`https://www.imdb.com/title/${tt}/`}>IMDb {tt}</a>
          </>
        )}
      </>,
    ],
  ]
  return (
    <>
      <TableBox label="Film facts">
        <table className="grid-table facts">
          <caption className="sr-only">Film facts</caption>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableBox>
      {f.baseline === true && (
        <p className="text-small">
          <span aria-hidden="true">{f.baseline_is_rental === true ? '‡' : '†'}</span> Includes{' '}
          {num(f.pre1982_baseline_gross) !== null && <b>{money(num(f.pre1982_baseline_gross)!)}</b>}{' '}
          {f.baseline_is_rental === true ? 'in film rentals (not gross)' : 'in gross'} from before 1982, when our
          weekend charts begin. Source: {str(f.baseline_source) ?? 'see the data notes'}.
        </p>
      )}
    </>
  )
}

function Slice({ rows, titleId, measure, factor }: { rows: Row[]; titleId: string; measure: 'nominal' | 'cpi' | 'admissions'; factor: number | null }) {
  return (
    <TableBox label="Leaderboard around this film">
      <table className="grid-table w-full">
        <caption className="sr-only">The all-time list around this film, by {MEASURE_LONG[measure]}</caption>
        <thead>
          <tr>
            <th scope="col" className="num">
              Rank
            </th>
            <th scope="col">Title</th>
            <th scope="col" className="num">
              Year
            </th>
            <th scope="col" className="num">
              {MEASURE_NAMES[measure]}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const me = r.title_id === titleId
            return (
              <tr key={String(r.title_id)} className={me ? 'hl' : undefined} aria-current={me ? 'true' : undefined}>
                <th scope="row" className="num">
                  {num(r.rank)}
                </th>
                <td>
                  {me ? <b>{String(r.title)}</b> : <FilmLink id={r.title_id} title={r.title} />}
                  <BaselineMark baseline={r.baseline} rental={r.baseline_is_rental} />
                </td>
                <td className="num">{num(r.year)}</td>
                <td className="num">{measureValue(measure, num(r.value), factor)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </TableBox>
  )
}

function Weekends({ rows, highlight }: { rows: Row[]; highlight: Day | null }) {
  const multi = new Set(rows.map((r) => r.release_id)).size > 1
  return (
    <TableBox label="Weekend by weekend" maxHeight={480}>
      <table className="grid-table w-full">
        <caption className="sr-only">Every weekend chart the film appeared on</caption>
        <thead>
          <tr>
            <th scope="col">Weekend</th>
            {multi && <th scope="col">Release</th>}
            <th scope="col" className="num">
              Rank
            </th>
            <th scope="col" className="num">
              Weekend gross
            </th>
            <th scope="col" className="num">
              Change
            </th>
            <th scope="col" className="num">
              Theaters
            </th>
            <th scope="col" className="num">
              Total gross
            </th>
            <th scope="col" className="num">
              Week
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const day = str(r.weekend_end)!
            const here = day === highlight
            return (
              <tr key={`${day}:${String(r.release_id)}`} className={here ? 'hl' : undefined}>
                <th scope="row">
                  <Link to={`/weekend?date=${day}`}>{shortDay(day)}</Link>
                </th>
                {multi && <td>{str(r.label) ?? 'Original'}</td>}
                <td className="num">{num(r.rank) ?? '–'}</td>
                <td className="num">
                  {num(r.weekend_gross) === null ? '–' : money(num(r.weekend_gross)!)}
                  <EstimateMark estimate={r.is_estimate} />
                </td>
                <td className="num">{pctChange(num(r.weekend_gross), num(r.last_weekend_gross)) ?? '–'}</td>
                <td className="num">{num(r.theaters) === null ? '–' : count(num(r.theaters)!)}</td>
                <td className="num">{num(r.total_gross) === null ? '–' : money(num(r.total_gross)!)}</td>
                <td className="num">{num(r.weeks) ?? '–'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </TableBox>
  )
}

function Releases({ rows }: { rows: Row[] }) {
  return (
    <TableBox label="Releases">
      <table className="grid-table w-full">
        <caption className="sr-only">The film&rsquo;s releases</caption>
        <thead>
          <tr>
            <th scope="col">Release</th>
            <th scope="col">Opened</th>
            <th scope="col">Distributor</th>
            <th scope="col" className="num">
              Weekends
            </th>
            <th scope="col" className="num">
              Last charted total
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r.release_id)}>
              <th scope="row">
                {str(r.label) ?? 'Original release'}
                {str(r.title) && <span className="text-muted"> ({str(r.title)})</span>}
              </th>
              <td>{str(r.release_date) ? shortDay(str(r.release_date)!) : str(r.first_weekend) ? shortDay(str(r.first_weekend)!) : '–'}</td>
              <td>{str(r.distributor) ?? '–'}</td>
              <td className="num">{num(r.weekends) ?? '–'}</td>
              <td className="num">{num(r.total_gross) === null ? '–' : money(num(r.total_gross)!)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableBox>
  )
}

export default function Film() {
  const { titleId = '' } = useParams()
  const navigate = useNavigate()
  const { measure, cpiBasis, link } = useView()
  const { asOf, latest, error: latestError } = useAsOf()
  const filmQ = useQuery(film({ titleId }))
  const creditsQ = useQuery(filmCredits({ titleId }))
  const f = filmQ.rows?.[0]
  const cpiToday = useCpiDollars('today', asOf)
  const cpi = useCpiDollars(cpiBasis, asOf)
  const mine = useQuery(asOf && f ? leaderboard({ asOf, measure, titleId }) : null)
  const me = mine.rows?.[0]
  const rank = num(me?.all_time_rank)
  const slice = useQuery(asOf && rank ? leaderboard({ asOf, measure, limit: 21, offset: Math.max(0, rank - 11) }) : null)
  const timeline = useQuery(f ? filmRankTimeline({ titleId, measure }) : null)
  const weekends = useQuery(f ? filmWeekends({ titleId }) : null)
  const releases = useQuery(f ? filmReleases({ titleId }) : null)
  const error = filmQ.error ?? latestError ?? mine.error ?? slice.error ?? timeline.error ?? weekends.error ?? releases.error

  const title = f ? `${String(f.title)} (${String(f.year)})` : null
  const points = useMemo(
    () => (timeline.rows ?? []).map((r) => ({ day: String(r.as_of), rank: num(r.rank) })),
    [timeline.rows],
  )
  const highlightWeekend = useMemo(() => {
    if (!asOf || !weekends.rows) return null
    let best: Day | null = null
    for (const r of weekends.rows) {
      const d = str(r.weekend_end)
      if (d && d <= asOf && (best === null || d > best)) best = d
    }
    return best
  }, [asOf, weekends.rows])

  const notFound = filmQ.rows !== undefined && !f
  const firstDay = str(f?.first_as_of)

  return (
    <>
      <PageHead
        section="Film"
        crumbs={[
          { label: 'Films', to: '/films' },
          ...(f ? [{ label: letterOf(String(f.title)), to: `/films?letter=${encodeURIComponent(letterOf(String(f.title)))}` }] : []),
          { label: title ?? titleId },
        ]}
        title={title ?? (notFound ? 'Film not found' : 'Film')}
        docTitle={title ?? null}
      >
        <p>
          Pick a date to see where this film stood among all the films in our charts on that day: by box
          office gross in the dollars of the day, by gross adjusted for inflation, or by estimated tickets
          sold. The chart and the weekend-by-weekend table come from the weekend charts as they were
          published, from 1982 to now.
        </p>
      </PageHead>

      {error && <ErrorBox error={error} />}
      {notFound && (
        <p>
          We have no film with the ID <code>{titleId}</code>. Try the search box, or <Link to="/films">browse films A to Z</Link>.
        </p>
      )}
      {!f && !notFound && !error && <LoadingBox what="the film" minHeight={420} />}

      {f && (
        <>
          <Facts f={f} credits={creditsQ.rows} cpiToday={cpiToday} />

          <SectionBar>Time machine</SectionBar>
          {asOf && latest ? <ViewControls asOf={asOf} latest={latest} cpi={cpi} /> : <ControlsSlot />}
          {!(asOf && mine.rows) && (
            <p className="summary" aria-hidden="true">
              &nbsp;
              <br />
              &nbsp;
            </p>
          )}
          {asOf && mine.rows && (
            <p className="summary">
              {me && rank ? (
                <>
                  On <b>{longDay(asOf)}</b>, <b>{String(f.title)}</b> ranked <b>{ordinal(rank)}</b> of all time by{' '}
                  {MEASURE_LONG[measure]}, with <b>{measureValue(measure, num(me.value), cpi.factor)}</b>
                  {measure === 'cpi' ? ` (${cpi.label})` : measure === 'admissions' ? ' tickets' : ''}.
                </>
              ) : firstDay && asOf < firstDay ? (
                <>
                  On {longDay(asOf)}, {String(f.title)} hadn&rsquo;t reached our charts yet (its first was{' '}
                  {shortDay(firstDay)}).
                </>
              ) : (
                <>
                  On {longDay(asOf)}, {String(f.title)} has no {MEASURE_NAMES[measure]} figure in our data.
                </>
              )}
            </p>
          )}
          {slice.rows && slice.rows.length > 0 && (
            <>
              <h2 className="sub-bar">The all-time list around it</h2>
              <Slice rows={slice.rows} titleId={titleId} measure={measure} factor={cpi.factor} />
              <p className="text-small">
                <Link to={`/leaderboard${link({ hl: titleId, page: rank ? Math.ceil(rank / 100) : null })}`}>
                  See it on the full leaderboard »
                </Link>
              </p>
            </>
          )}
          {(mine.loading || slice.loading || !asOf) && !slice.rows && <LoadingBox what="the rankings" minHeight={620} />}

          <SectionBar>Rank over time</SectionBar>
          {timeline.rows ? (
            points.length ? (
              <figure className="m-0 mb-3">
                <Suspense fallback={<div className="chart-box" style={{ height: 262 }} />}>
                  <RankChart
                    points={points}
                    end={latest ?? points[points.length - 1]!.day}
                    selected={asOf ?? points[0]!.day}
                    onPick={(day) => navigate(link({ date: day }))}
                  />
                </Suspense>
                <figcaption className="text-small">
                  All-time rank by {MEASURE_LONG[measure]}, from its first chart to{' '}
                  {latest ? shortDay(latest) : 'now'} (rank 1 at the top; the dashed line marks the date
                  shown). Click the chart to jump to a date.
                </figcaption>
                <details className="mt-1">
                  <summary>Rank history as a table ({points.length} changes)</summary>
                  <TableBox label="Rank history" maxHeight={320}>
                    <table className="grid-table">
                      <caption className="sr-only">Each date the film&rsquo;s all-time rank changed</caption>
                      <thead>
                        <tr>
                          <th scope="col">From</th>
                          <th scope="col" className="num">
                            Rank
                          </th>
                          <th scope="col" className="num">
                            {MEASURE_NAMES[measure]}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {timeline.rows.map((r) => (
                          <tr key={String(r.as_of)}>
                            <th scope="row">
                              <Link to={link({ date: String(r.as_of) })}>{shortDay(String(r.as_of))}</Link>
                            </th>
                            <td className="num">{num(r.rank) ?? '–'}</td>
                            <td className="num">{measureValue(measure, num(r.value), cpi.factor)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableBox>
                </details>
              </figure>
            ) : (
              <p>No {MEASURE_NAMES[measure]} figures for this film.</p>
            )
          ) : (
            !error && <LoadingBox what="the rank history" minHeight={340} />
          )}

          <SectionBar>Weekend by weekend</SectionBar>
          {weekends.rows ? (
            weekends.rows.length ? (
              <>
                <Weekends rows={weekends.rows} highlight={highlightWeekend} />
                <FlagLegend estimate={weekends.rows.some((r) => r.is_estimate === true)} />
              </>
            ) : (
              <p>This film has no weekend charts in our data{f.baseline === true ? ' (its total comes from before 1982)' : ''}.</p>
            )
          ) : (
            !error && <LoadingBox what="the weekend charts" minHeight={500} />
          )}

          {releases.rows && releases.rows.length > 0 && (
            <>
              <SectionBar>Releases</SectionBar>
              <Releases rows={releases.rows} />
            </>
          )}
          <p className="text-small">
            <Link to={`/leaderboard${link({ hl: null })}`}>The all-time leaderboard on this date »</Link>
          </p>
        </>
      )}
    </>
  )
}
