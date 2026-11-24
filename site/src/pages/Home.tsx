import { Fragment } from 'react'
import { Link } from 'react-router'
import { FilmLink, num, str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import { BaselineMark, FlagLegend } from '../components/Flags'
import LoadingBox from '../components/LoadingBox'
import { useTitle } from '../components/PageHead'
import SearchBox from '../components/SearchBox'
import SectionBar from '../components/SectionBar'
import TableBox from '../components/TableBox'
import { useQuery } from '../db/useQuery'
import { addYears, today } from '../lib/dates'
import { longDay, money } from '../lib/format'
import { useLatestDate, useView } from '../lib/view'
import { leaderboard, weekendChart } from '../queries'

const YEARS_AGO = [10, 20, 30, 40] as const
const DEFAULT_AGO = 30
const TOP = 10

function TopTen() {
  const { latest, error: latestError } = useLatestDate()
  const q = useQuery(latest ? leaderboard({ asOf: latest, measure: 'nominal', limit: TOP }) : null)
  const error = q.error ?? latestError
  if (error) return <ErrorBox error={error} />
  if (!q.rows || !latest) return <LoadingBox what="the all-time top 10" minHeight={330} />
  const then = (years: number) => `/leaderboard?date=${addYears(latest, -years)}`
  return (
    <>
      <TableBox label="All-time top 10">
        <table className="grid-table w-full">
          <caption>All-time top {TOP} as of {longDay(latest)}, by box office gross</caption>
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
                Total gross
              </th>
            </tr>
          </thead>
          <tbody>
            {q.rows.map((r) => (
              <tr key={String(r.title_id)}>
                <th scope="row" className="num">
                  {num(r.rank)}
                </th>
                <td>
                  <FilmLink id={r.title_id} title={r.title} />
                  <BaselineMark baseline={r.baseline} rental={r.baseline_is_rental} />
                </td>
                <td className="num">{num(r.year)}</td>
                <td className="num">{money(num(r.value) ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableBox>
      <FlagLegend baseline={q.rows.some((r) => r.baseline === true && r.baseline_is_rental !== true)} rental={q.rows.some((r) => r.baseline_is_rental === true && r.baseline === true)} />
      <p>
        <Link to="/leaderboard">Full leaderboard »</Link> · <Link to="/leaderboard?m=cpi">Adjusted for inflation »</Link> ·{' '}
        <Link to="/leaderboard?m=admissions">By tickets sold »</Link>
        <br />
        The same list as it stood in{' '}
        {[10, 20, 30, 40].map((y, i) => (
          <Fragment key={y}>
            {i > 0 && ', '}
            <Link to={then(y)}>{Number(latest.slice(0, 4)) - y}</Link>
          </Fragment>
        ))}
        .
      </p>
    </>
  )
}

function ThisWeekend() {
  const { params, link } = useView()
  const asked = Number(params.get('ago'))
  const ago = (YEARS_AGO as readonly number[]).includes(asked) ? asked : DEFAULT_AGO
  const onDate = addYears(today(), -ago)
  const q = useQuery(weekendChart({ onDate }))
  const weekend = str(q.rows?.[0]?.weekend_end)
  return (
    <>
      <nav aria-label="Years ago" className="mb-2">
        <span className="font-bold">Go back:</span>{' '}
        {YEARS_AGO.map((y, i) => (
          <Fragment key={y}>
            {i > 0 && <span aria-hidden="true"> | </span>}
            {y === ago ? (
              <b aria-current="true" className="current-choice">
                {y} years
              </b>
            ) : (
              <Link to={link({ ago: y === DEFAULT_AGO ? null : y })} preventScrollReset>
                {y} years
              </Link>
            )}
          </Fragment>
        ))}
      </nav>
      {q.error && <ErrorBox error={q.error} />}
      {!q.rows && !q.error && <LoadingBox what="the weekend chart" minHeight={330} />}
      {q.rows && weekend && (
        <>
          <TableBox label="This weekend in history">
            <table className="grid-table w-full">
              <caption>Weekend ending {longDay(weekend)}</caption>
              <thead>
                <tr>
                  <th scope="col" className="num">
                    Rank
                  </th>
                  <th scope="col">Title</th>
                  <th scope="col" className="num">
                    Weekend gross
                  </th>
                  <th scope="col" className="num">
                    Total gross
                  </th>
                </tr>
              </thead>
              <tbody>
                {q.rows.slice(0, TOP).map((r) => (
                  <tr key={String(r.release_id)}>
                    <th scope="row" className="num">
                      {num(r.rank) ?? '–'}
                    </th>
                    <td>
                      {str(r.title_id) ? <FilmLink id={r.title_id} title={str(r.charted_title) ?? r.title} /> : str(r.charted_title)}
                      {num(r.weeks) === 1 && num(r.last_rank) === null && <span className="badge-new ml-1">NEW!</span>}
                    </td>
                    <td className="num">{num(r.weekend_gross) === null ? '–' : money(num(r.weekend_gross)!)}</td>
                    <td className="num">{num(r.total_gross) === null ? '–' : money(num(r.total_gross)!)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
          <p>
            <Link to={`/weekend?date=${weekend}`}>The whole chart for that weekend »</Link>
          </p>
        </>
      )}
    </>
  )
}

export default function Home() {
  useTitle(null)
  return (
    <>
      <SectionBar>Welcome</SectionBar>
      <h1>Box office history, as it happened</h1>
      <p>
        Welcome, traveler! BoxOfficeBozo is a time machine for the movies. Pick any date since 1982 and see
        the all-time box office lists exactly as they stood that day: by gross in the dollars of the day,
        by gross adjusted for inflation, or by estimated tickets sold. Look up any film to watch it climb
        the charts, or any director or actor to see their career total on any date.
      </p>
      <div className="box mb-3 p-2">
        <SearchBox size="big" />
      </div>

      <SectionBar>The all-time top 10 today</SectionBar>
      <TopTen />

      <SectionBar>This weekend in history</SectionBar>
      <ThisWeekend />
    </>
  )
}
