import { Fragment } from 'react'
import { Link } from 'react-router'

export const LETTERS = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'] as const

/** # A B C ... Z, linking to the film list for each letter. */
export default function LetterBar({ current }: { current?: string | null }) {
  return (
    <nav aria-label="Films A to Z" className="letter-bar mb-3">
      {LETTERS.map((l, i) => (
        <Fragment key={l}>
          {i > 0 && ' '}
          {l === current ? (
            <b aria-current="page">{l}</b>
          ) : (
            <Link to={`/films?letter=${encodeURIComponent(l)}`}>
              {l}
              {l === '#' && <span className="sr-only"> (numbers and symbols)</span>}
            </Link>
          )}
        </Fragment>
      ))}
    </nav>
  )
}
