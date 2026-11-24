import { useSyncExternalStore } from 'react'
import { ENGINE_TASK, getProgress, subscribeProgress } from '../db/store'

function mb(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`
}

/**
 * The 90s "Loading... please wait" box, with a progress bar over everything the site is still
 * downloading. `minHeight` reserves the space the result will take, so nothing jumps.
 */
export default function LoadingBox({ what, minHeight }: { what: string; minHeight?: number }) {
  const p = useSyncExternalStore(subscribeProgress, getProgress, getProgress)
  const pct = p.total > 0 ? Math.min(100, Math.floor((p.done / p.total) * 100)) : 0
  const pending = p.pending.map((t) => (t === ENGINE_TASK ? t : `${t} table`))
  return (
    <div className="box mb-3" style={minHeight ? { minHeight } : undefined}>
      <div className="bar text-body">Loading… please wait</div>
      <div className="p-2">
        <p role="status" className="mb-2">
          Loading {what}…
        </p>
        <div
          className="progress"
          role="progressbar"
          aria-label={`Loading ${what}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={p.busy ? pct : undefined}
        >
          <div className="progress-fill" style={{ width: `${p.busy ? pct : 100}%` }} />
        </div>
        <p className="mb-0 mt-1 text-small text-muted">
          {p.busy
            ? `${pct}% · downloading ${pending.join(', ')}${p.tableBytes ? ` (${mb(p.tableBytes)} of tables)` : ''}`
            : 'Crunching the numbers…'}
        </p>
        <p className="mb-0 mt-2 text-small">
          Your first visit downloads a small database engine and the box office tables. After that,
          every ranking for every date is worked out right here in your browser.
        </p>
      </div>
    </div>
  )
}
