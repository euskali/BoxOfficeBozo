import { Fragment, useId, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { addDays, addYears, FIRST_DAY, sundayOnOrBefore } from '../lib/dates'
import { longDay, MEASURE_NAMES } from '../lib/format'
import { useView, type CpiDollars } from '../lib/view'
import { MEASURES, type Day } from '../queries'

/** A step link: its visible text plus words for screen readers ("« 1 yr" + " earlier"). */
function StepLink({ to, enabled, children, more }: { to: string; enabled: boolean; children: ReactNode; more?: string }) {
  return enabled ? (
    <Link to={to}>
      {children}
      {more && <span className="sr-only"> {more}</span>}
    </Link>
  ) : (
    <span className="text-muted" aria-hidden="true">
      {children}
    </span>
  )
}

/**
 * Holds the controls' place until the latest date is known, so nothing below jumps when they
 * appear.
 */
export function ControlsSlot({ height = 104 }: { height?: number }) {
  return <div className="box controls mb-3" style={{ minHeight: height }} aria-hidden="true" />
}

/**
 * The time machine's controls: a date (snapped back to that weekend's Sunday), steps of a week and
 * a year, and the measure. Everything is a link or a GET-style form, so each view has a URL.
 */
export default function ViewControls({
  asOf,
  latest,
  measures = true,
  cpi,
  children,
}: {
  asOf: Day
  latest: Day
  /** Show the measure switch. */
  measures?: boolean
  /** Show the CPI basis switch (when the measure is CPI). */
  cpi?: CpiDollars
  children?: ReactNode
}) {
  const { link, measure, cpiBasis } = useView()
  const navigate = useNavigate()
  const dateId = useId()

  function go(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const value = new FormData(e.currentTarget).get('date')
    if (typeof value !== 'string' || !value) return
    const snapped = sundayOnOrBefore(value < FIRST_DAY ? FIRST_DAY : value > latest ? latest : value)
    navigate(link({ date: snapped >= latest ? null : snapped < FIRST_DAY ? FIRST_DAY : snapped }))
  }

  const at = (d: Day) => (d >= latest ? null : d < FIRST_DAY ? FIRST_DAY : d)
  const steps = [
    { label: '« 1 yr', more: 'earlier', day: addYears(asOf, -1), ok: asOf > FIRST_DAY },
    { label: '‹ 1 wk', more: 'earlier', day: addDays(asOf, -7), ok: asOf > FIRST_DAY },
    { label: '1 wk ›', more: 'later', day: addDays(asOf, 7), ok: asOf < latest },
    { label: '1 yr »', more: 'later', day: addYears(asOf, 1), ok: asOf < latest },
  ]

  return (
    <div className="box controls mb-3 p-2">
      <form onSubmit={go} className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span>
          <label htmlFor={dateId} className="mr-1 font-bold">
            Date:
          </label>
          <input
            id={dateId}
            key={asOf}
            type="date"
            name="date"
            defaultValue={asOf}
            min={FIRST_DAY}
            max={latest}
            required
          />{' '}
          <button type="submit" className="btn-bevel">
            [ Go ]
          </button>
        </span>
        <span className="steps">
          {steps.map((s, i) => (
            <Fragment key={s.label}>
              {i > 0 && <span aria-hidden="true"> | </span>}
              <StepLink to={link({ date: at(s.day) })} enabled={s.ok} more={s.more}>
                {s.label}
              </StepLink>
            </Fragment>
          ))}
          <span aria-hidden="true"> | </span>
          <StepLink to={link({ date: null })} enabled={asOf !== latest} more="weekend">
            Latest
          </StepLink>
        </span>
      </form>
      <p className="mb-0 mt-2">
        Showing: <b>{longDay(asOf)}</b>
        {asOf === latest && <span className="text-muted"> (latest weekend in the data)</span>}
      </p>
      {measures && (
        <nav aria-label="Measure" className="mt-2">
          <span className="font-bold">Measure:</span>{' '}
          {MEASURES.map((m, i) => (
            <Fragment key={m}>
              {i > 0 && <span aria-hidden="true"> | </span>}
              {m === measure ? (
                <b aria-current="true" className="current-choice">
                  {MEASURE_NAMES[m]}
                </b>
              ) : (
                <Link to={link({ m })}>{MEASURE_NAMES[m]}</Link>
              )}
            </Fragment>
          ))}
        </nav>
      )}
      {cpi && measure === 'cpi' && (
        <nav aria-label="Dollars of" className="mt-1">
          <span className="font-bold">Dollars of:</span>{' '}
          {cpiBasis === 'today' ? (
            <b aria-current="true" className="current-choice">
              Today
            </b>
          ) : (
            <Link to={link({ cpi: null })}>Today</Link>
          )}
          <span aria-hidden="true"> | </span>
          {cpiBasis === 'then' ? (
            <b aria-current="true" className="current-choice">
              That date
            </b>
          ) : (
            <Link to={link({ cpi: 'then' })}>That date</Link>
          )}
          {cpi.month && (
            <span className="text-muted">
              {' '}
              ({cpi.label}
              {cpi.interpolated ? ', CPI interpolated' : ''})
            </span>
          )}
        </nav>
      )}
      {children}
    </div>
  )
}
