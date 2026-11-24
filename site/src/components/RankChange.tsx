/** Rank change against an earlier list: ▲3, ▼2, – or NEW. Never color alone: arrows and words too. */
export default function RankChange({ rank, prev }: { rank: number; prev: number | null }) {
  if (prev === null) {
    return (
      <span className="badge-new">
        NEW<span className="sr-only"> on the list</span>
      </span>
    )
  }
  const diff = prev - rank
  if (diff === 0) {
    return (
      <span>
        <span aria-hidden="true">–</span>
        <span className="sr-only">no change</span>
      </span>
    )
  }
  const up = diff > 0
  return (
    <span className={up ? 'move-up' : 'move-down'}>
      <span aria-hidden="true">{up ? '▲' : '▼'}</span>
      {Math.abs(diff).toLocaleString('en-US')}
      <span className="sr-only">{up ? ' places up' : ' places down'}</span>
    </span>
  )
}
