import { useId, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { FilmLink, num, str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import { EstimateMark, FlagLegend } from '../components/Flags'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import TableBox from '../components/TableBox'
import { useQuery } from '../db/useQuery'
import { addYears, FIRST_DAY, parseDay, today } from '../lib/dates'
import { count, longDay, money, pctChange, shortDay } from '../lib/format'
import { useView } from '../lib/view'
import { weekendChart } from '../queries'

const SOURCES: Record<string, string> = {
  stat695: 'the Purdue STAT 695 dataset (Box Office Mojo weekend charts, compiled March 2017)',
  wayback: 'an archived Box Office Mojo page (Internet Archive Wayback Machine)',
  commoncrawl: 'an archived Box Office Mojo page (Common Crawl)',
}

export default function Weekend() {
  const { params } = useView()
  const navigate = useNavigate()
  const dateId = useId()
  const asked = parseDay(params.get('date'))
  const onDate = asked ?? today()
  const q = useQuery(weekendChart({ onDate }))
  const rows = q.rows
  const first = rows?.[0]
  const weekend = str(first?.weekend_end)
  const prev = str(first?.prev_weekend_end)
  const next = str(first?.next_weekend_end)
  const captures = [...new Set((rows ?? []).map((r) => str(r.capture_url)).filter((u): u is string => u !== null))]
  const sources = [...new Set((rows ?? []).map((r) => str(r.source)).filter((s): s is string => s !== null))]
  const title = weekend ? `Weekend box office: ${longDay(weekend)}` : 'Weekend box office charts'

  function go(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const v = new FormData(e.currentTarget).get('date')
    if (typeof v === 'string' && v) navigate(`/weekend?date=${v}`)
  }

  return (
    <>
      <PageHead
        section="Weekend Charts"
        crumbs={[{ label: 'Weekend Charts', to: '/weekend' }, ...(weekend ? [{ label: weekend.slice(0, 4) }, { label: shortDay(weekend) }] : [])]}
        title={title}
        docTitle={weekend ? `Weekend of ${shortDay(weekend)}` : 'Weekend charts'}
      >
        <p>
          The weekend chart as it was published, for any weekend from January 1982 to the most recent one:
          each film&rsquo;s rank, its gross for the weekend, the change from the weekend before, its theater
          count and its running total. Pick a date and we&rsquo;ll show the chart for the weekend ending on or
          before it.
        </p>
      </PageHead>

      <div className="box controls mb-3 p-2">
        <form onSubmit={go} className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span>
            <label htmlFor={dateId} className="mr-1 font-bold">
              Date:
            </label>
            <input id={dateId} key={weekend ?? onDate} type="date" name="date" defaultValue={weekend ?? onDate} min={FIRST_DAY} max={today()} required />{' '}
            <button type="submit" className="btn-bevel">
              [ Go ]
            </button>
          </span>
          {weekend && (
            <span>
              {prev ? <Link to={`/weekend?date=${prev}`}>‹ Previous weekend</Link> : <span className="text-muted">‹ Previous weekend</span>}
              <span aria-hidden="true"> | </span>
              {next ? <Link to={`/weekend?date=${next}`}>Next weekend ›</Link> : <span className="text-muted">Next weekend ›</span>}
              <span aria-hidden="true"> | </span>
              <Link to={`/weekend?date=${addYears(weekend, -1)}`}>A year earlier</Link>
              <span aria-hidden="true"> | </span>
              <Link to="/weekend">Latest</Link>
            </span>
          )}
        </form>
      </div>

      {q.error && <ErrorBox error={q.error} />}
      {!rows && !q.error && <LoadingBox what="the weekend chart" minHeight={600} />}
      {rows && rows.length === 0 && <p>There are no charts before the weekend of {longDay('1982-01-03')}.</p>}

      {rows && weekend && rows.length > 0 && (
        <>
          <h2 className="sub-bar">
            Weekend ending {longDay(weekend)}
            {q.stale && <span className="font-normal"> (updating…)</span>}
          </h2>
          <TableBox label="Weekend chart">
            <table className="grid-table w-full">
              <caption className="sr-only">Weekend box office chart for the weekend ending {longDay(weekend)}</caption>
              <thead>
                <tr>
                  <th scope="col" className="num">
                    <abbr title="This weekend">TW</abbr>
                  </th>
                  <th scope="col" className="num">
                    <abbr title="Last weekend">LW</abbr>
                  </th>
                  <th scope="col">Title</th>
                  <th scope="col">Studio</th>
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
                  const isNew = num(r.weeks) === 1 && num(r.last_rank) === null
                  const charted = str(r.charted_title)
                  return (
                    <tr key={String(r.release_id)}>
                      <th scope="row" className="num">
                        {num(r.rank) ?? '–'}
                      </th>
                      <td className="num">{isNew ? <span className="badge-new">NEW!</span> : (num(r.last_rank) ?? '–')}</td>
                      <td>
                        {str(r.title_id) ? <FilmLink id={r.title_id} title={charted ?? r.title} /> : (charted ?? '–')}
                      </td>
                      <td>{str(r.distributor) ?? '–'}</td>
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
          <FlagLegend estimate={rows.some((r) => r.is_estimate === true)} />
          <p className="text-small">
            Source: {sources.map((s) => SOURCES[s] ?? s).join('; ')}.
            {captures.length > 0 && (
              <>
                {' '}
                Archived page{captures.length === 1 ? '' : 's'}:{' '}
                {captures.map((u, i) => (
                  <span key={u}>
                    {i > 0 && ', '}
                    <a href={u}>capture {i + 1}</a>
                  </span>
                ))}
                .
              </>
            )}{' '}
            Totals are each release&rsquo;s running total as charted that weekend. &ldquo;Change&rdquo; compares with
            the release&rsquo;s gross on the chart before, when that chart was within 10 days.
          </p>
        </>
      )}
    </>
  )
}
