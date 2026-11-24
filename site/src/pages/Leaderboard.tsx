import { useId, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { BaselineMark, FlagLegend } from '../components/Flags'
import { FilmLink, hasBaseline, MeasureHeader, num } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import Pager from '../components/Pager'
import RankChange from '../components/RankChange'
import TableBox from '../components/TableBox'
import ViewControls, { ControlsSlot } from '../components/ViewControls'
import { useQuery } from '../db/useQuery'
import { addYears } from '../lib/dates'
import { count, longDay, MEASURE_LONG, measureValue, money, shortDay } from '../lib/format'
import { useAsOf, useCpiDollars, useView } from '../lib/view'
import { leaderboard } from '../queries'

const PAGE_SIZE = 100

function parseYear(s: string | null): number | null {
  if (!s || !/^\d{4}$/.test(s)) return null
  return Number(s)
}

function YearFilter({ fromYear, toYear }: { fromYear: number | null; toYear: number | null }) {
  const { link } = useView()
  const navigate = useNavigate()
  const fromId = useId()
  const toId = useId()
  function go(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    navigate(link({ from: parseYear(String(f.get('from') ?? '')), to: parseYear(String(f.get('to') ?? '')), page: null }))
  }
  return (
    <form onSubmit={go} className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-bold">Released:</span>
      <label htmlFor={fromId}>from</label>
      <input id={fromId} key={`f${fromYear}`} name="from" type="number" min={1900} max={2100} defaultValue={fromYear ?? ''} className="w-[5.5em]" />
      <label htmlFor={toId}>to</label>
      <input id={toId} key={`t${toYear}`} name="to" type="number" min={1900} max={2100} defaultValue={toYear ?? ''} className="w-[5.5em]" />
      <button type="submit" className="btn-bevel">
        [ Filter ]
      </button>
    </form>
  )
}

export default function Leaderboard() {
  const { params, measure, cpiBasis, link } = useView()
  const { asOf, latest, error: latestError } = useAsOf()
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1)
  const fromYear = parseYear(params.get('from'))
  const toYear = parseYear(params.get('to'))
  const hl = params.get('hl')
  const cpi = useCpiDollars(cpiBasis, asOf)
  const compareTo = asOf ? addYears(asOf, -1) : null
  const q = useQuery(
    asOf
      ? leaderboard({ asOf, measure, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, fromYear, toYear, compareTo })
      : null,
  )
  const rows = q.rows
  const error = q.error ?? latestError
  const total = num(rows?.[0]?.matching) ?? 0
  const years =
    fromYear !== null || toYear !== null
      ? ` released ${fromYear !== null && toYear !== null ? `${fromYear}–${toYear}` : fromYear !== null ? `${fromYear} or later` : `${toYear} or earlier`}`
      : ''

  return (
    <>
      <PageHead section="All-Time Leaderboard" crumbs={[{ label: 'Leaderboard' }]} title="All-time domestic box office, as of any date">
        <p>
          The top films of all time at US and Canadian theaters, ranked as the lists stood on the date you
          pick. Switch between box office gross in the dollars of the day, gross adjusted for inflation, and
          estimated tickets sold, and see how each film moved since the same date a year before.
        </p>
      </PageHead>

      {asOf && latest ? (
        <ViewControls asOf={asOf} latest={latest} cpi={cpi}>
          <YearFilter fromYear={fromYear} toYear={toYear} />
        </ViewControls>
      ) : (
        !error && <ControlsSlot height={136} />
      )}

      {error && <ErrorBox error={error} />}
      {!rows && !error && <LoadingBox what="the leaderboard" minHeight={600} />}

      {rows && asOf && (
        <>
          <h2 className="sub-bar">
            Top {measure === 'admissions' ? 'films by tickets sold' : 'grossing films'}
            {years}, as of {longDay(asOf)}
            {q.stale && <span className="font-normal"> (updating…)</span>}
          </h2>
          {rows.length === 0 ? (
            <p>No films match{years ? ' those years' : ''} on this date. Our charts start in 1982.</p>
          ) : (
            <>
              <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
              <TableBox label="Leaderboard">
                <table className="grid-table w-full">
                  <caption className="sr-only">
                    All-time leaderboard{years} as of {longDay(asOf)}, ranked by {MEASURE_LONG[measure]}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="num">
                        Rank
                      </th>
                      <th scope="col">
                        vs {compareTo ? shortDay(compareTo) : ''}
                      </th>
                      <th scope="col">Title</th>
                      <th scope="col" className="num">
                        Year
                      </th>
                      <MeasureHeader m="nominal" current={measure} href={link({ m: 'nominal', page: null })} />
                      <MeasureHeader m="cpi" current={measure} href={link({ m: 'cpi', page: null })} label={`CPI-adj. (${cpi.label})`} />
                      <MeasureHeader m="admissions" current={measure} href={link({ m: 'admissions', page: null })} />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={String(r.title_id)} className={r.title_id === hl ? 'hl' : undefined}>
                        <th scope="row" className="num">
                          {num(r.rank)}
                        </th>
                        <td>
                          <RankChange rank={num(r.rank) ?? 0} prev={num(r.prev_rank)} />
                        </td>
                        <td>
                          <FilmLink id={r.title_id} title={r.title} />
                          <BaselineMark baseline={r.baseline} rental={r.baseline_is_rental} />
                        </td>
                        <td className="num">{num(r.year)}</td>
                        <td className={measure === 'nominal' ? 'num sorted' : 'num'}>
                          {num(r.cume_nominal) === null ? '–' : money(num(r.cume_nominal)!)}
                        </td>
                        <td className={measure === 'cpi' ? 'num sorted' : 'num'}>
                          {measureValue('cpi', num(r.cume_cpi), cpi.factor)}
                        </td>
                        <td className={measure === 'admissions' ? 'num sorted' : 'num'}>
                          {num(r.cume_admissions) === null ? '–' : count(num(r.cume_admissions)!)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableBox>
              <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
              <FlagLegend baseline={hasBaseline(rows, false)} rental={hasBaseline(rows, true)} />
            </>
          )}
          <pre className="notes">{`DATA NOTES
==========
* "vs" compares each film's rank with its rank on
  the same date a year earlier, in the same list.
  NEW = not on the list then.
* CPI-adjusted dollars deflate each weekend's gross
  by that month's CPI-U (BLS), then show it in
  ${cpi.label}.
* Tickets are estimated: each weekend's gross
  divided by that year's average ticket price (some
  years interpolated).
* Charts start in 1982. Films released earlier
  count only from then, unless we have a sourced
  pre-1982 total (marked).`}</pre>
        </>
      )}
    </>
  )
}
