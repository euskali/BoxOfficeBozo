import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { sundayOnOrBefore } from '../lib/dates'
import { dayToDate, shortDay } from '../lib/format'

export interface RankPoint {
  day: string
  rank: number | null
}

const HEIGHT = 260
const LINE = '#003366'
const MARK = '#cc0000'
const INK = '#000000'
const GRID = '#cccccc'
const FONT = '11px Verdana, Tahoma, Geneva, sans-serif'

const toSec = (day: string) => dayToDate(day).getTime() / 1000
const toDay = (sec: number) => new Date(sec * 1000).toISOString().slice(0, 10)

/**
 * A film's all-time rank over time, as a plain step chart: white background, gray grid, one navy
 * line, rank 1 at the top on a log scale. Hovering shows a yellow tip; clicking picks that date.
 * It's a picture of the data the page also gives as a table, so it's hidden from screen readers.
 */
export default function RankChart({
  points,
  end,
  selected,
  onPick,
}: {
  points: RankPoint[]
  /** Extend the last step to this day (the latest in the data). */
  end: string
  selected: string
  onPick: (day: string) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const tip = useRef<HTMLDivElement>(null)
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    const el = box.current
    const tipEl = tip.current
    if (!el || !tipEl || points.length === 0) return
    const xs = points.map((p) => toSec(p.day))
    const ys: (number | null)[] = points.map((p) => p.rank)
    const last = points[points.length - 1]!
    if (end > last.day) {
      xs.push(toSec(end))
      ys.push(last.rank)
    }
    const ranks = ys.filter((r): r is number => r !== null)
    const worst = Math.max(10, ...ranks)
    const selectedSec = toSec(selected)

    const indexAt = (sec: number) => {
      let i = -1
      for (let k = 0; k < xs.length && xs[k]! <= sec; k++) i = k
      return i
    }

    const axis: uPlot.Axis = {
      stroke: INK,
      font: FONT,
      grid: { stroke: GRID, width: 1 },
      ticks: { stroke: GRID, width: 1 },
    }

    const opts: uPlot.Options = {
      width: el.clientWidth,
      height: HEIGHT,
      scales: {
        x: { time: true },
        y: { distr: 3, log: 10, dir: -1, range: [1, worst * 1.3] },
      },
      axes: [axis, { ...axis, size: 56, values: (_u, vals) => vals.map((v) => (v == null ? '' : `#${Math.round(v).toLocaleString('en-US')}`)) }],
      series: [
        {},
        {
          stroke: LINE,
          width: 2,
          paths: uPlot.paths.stepped!({ align: 1 }),
          points: { show: false },
          spanGaps: false,
        },
      ],
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false }, y: false },
      hooks: {
        draw: [
          (u) => {
            const ctx = u.ctx
            const { top, height } = u.bbox
            ctx.save()
            // square markers where the rank changes (when there aren't too many to see)
            if (points.length <= 250) {
              ctx.fillStyle = LINE
              const s = 3 * uPlot.pxRatio
              points.forEach((p) => {
                if (p.rank === null) return
                const x = u.valToPos(toSec(p.day), 'x', true)
                const y = u.valToPos(p.rank, 'y', true)
                ctx.fillRect(x - s, y - s, 2 * s, 2 * s)
              })
            }
            // the chosen date
            const x = u.valToPos(selectedSec, 'x', true)
            ctx.strokeStyle = MARK
            ctx.lineWidth = uPlot.pxRatio
            ctx.setLineDash([4 * uPlot.pxRatio, 3 * uPlot.pxRatio])
            ctx.beginPath()
            ctx.moveTo(x, top)
            ctx.lineTo(x, top + height)
            ctx.stroke()
            ctx.restore()
          },
        ],
        setCursor: [
          (u) => {
            const left = u.cursor.left ?? -1
            if (left < 0) {
              tipEl.hidden = true
              return
            }
            const sec = u.posToVal(left, 'x')
            const i = indexAt(sec)
            const rank = i >= 0 ? ys[i] : null
            tipEl.textContent = `${shortDay(toDay(sec))}: ${rank == null ? 'no rank' : `#${rank.toLocaleString('en-US')}`}`
            tipEl.hidden = false
            const plotLeft = u.over.offsetLeft
            const x = plotLeft + left
            tipEl.style.left = `${Math.min(x + 10, el.clientWidth - tipEl.offsetWidth - 2)}px`
            tipEl.style.top = `${u.over.offsetTop + 6}px`
          },
        ],
      },
    }

    const u = new uPlot(opts, [xs, ys], el)
    const click = () => {
      const left = u.cursor.left ?? -1
      if (left < 0) return
      pickRef.current(sundayOnOrBefore(toDay(u.posToVal(left, 'x'))))
    }
    u.over.addEventListener('click', click)
    u.over.style.cursor = 'crosshair'
    const ro = new ResizeObserver(() => u.setSize({ width: el.clientWidth, height: HEIGHT }))
    ro.observe(el)
    return () => {
      ro.disconnect()
      u.over.removeEventListener('click', click)
      u.destroy()
    }
  }, [points, end, selected])

  return (
    <div className="chart-box" aria-hidden="true">
      <div ref={box} className="relative" />
      <div ref={tip} className="chart-tip" hidden />
    </div>
  )
}
