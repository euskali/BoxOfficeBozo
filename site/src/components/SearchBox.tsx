import { useEffect, useId, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Row } from '../db/rows'
import { prefetch } from '../db/store'
import { useQuery } from '../db/useQuery'
import { search } from '../queries'

export function hitHref(hit: Row): string {
  return hit.kind === 'film' ? `/film/${String(hit.id)}` : `/person/${String(hit.id)}`
}

/** "director, 11 films · actor, 4 films" */
export function personDetail(hit: Row): string {
  const parts: string[] = []
  const directed = Number(hit.directed ?? 0)
  const acted = Number(hit.acted ?? 0)
  if (directed) parts.push(`director of ${directed} film${directed === 1 ? '' : 's'}`)
  if (acted) parts.push(`in the cast of ${acted} film${acted === 1 ? '' : 's'}`)
  return parts.join(' · ')
}

function hitLabel(hit: Row): string {
  return hit.kind === 'film' ? `${String(hit.name)}${hit.year ? ` (${String(hit.year)})` : ''}` : String(hit.name)
}

/**
 * Keyboard-first search over films and people (search.sql): type, arrow through the matches, Enter
 * to open one, or Enter with none picked for the full results page. Press "/" anywhere to jump here.
 */
export default function SearchBox({ size = 'small' }: { size?: 'small' | 'big' }) {
  const [text, setText] = useState('')
  const [typed, setTyped] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const navigate = useNavigate()
  const inputId = useId()
  const listId = useId()
  const helpId = useId()

  useEffect(() => {
    const t = setTimeout(() => setTyped(text.trim()), 120)
    return () => clearTimeout(t)
  }, [text])

  const q = useQuery(typed ? search({ text: typed, limit: 6 }) : null)
  const hits = typed && q.rows ? q.rows : []
  const showList = open && typed !== ''

  useEffect(() => setActive(-1), [typed])

  function pick(hit: Row) {
    setOpen(false)
    setText('')
    navigate(hitHref(hit))
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    const hit = active >= 0 ? hits[active] : undefined
    if (hit) pick(hit)
    else if (text.trim()) {
      setOpen(false)
      navigate(`/search?q=${encodeURIComponent(text.trim())}`)
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => (hits.length ? (a + 1) % hits.length : -1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (hits.length ? (a <= 0 ? hits.length - 1 : a - 1) : -1))
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
        setActive(-1)
      }
    }
  }

  const optionId = (i: number) => `${listId}-${i}`
  const films = hits.filter((h) => h.kind === 'film').length
  const people = hits.length - films

  return (
    <form role="search" onSubmit={submit} className={size === 'big' ? 'search-big' : undefined}>
      <label htmlFor={inputId} className="mb-1 block font-bold">
        Search films and people
      </label>
      <div className="relative flex gap-1">
        <input
          id={inputId}
          type="text"
          name="q"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? optionId(active) : undefined}
          aria-describedby={helpId}
          autoComplete="off"
          spellCheck={false}
          data-site-search=""
          value={text}
          placeholder={size === 'big' ? 'e.g. Titanic, Tom Hanks' : undefined}
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
          }}
          onFocus={() => {
            prefetch(search({ text: 'a' }))
            setOpen(true)
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          className="w-full min-w-0 flex-1"
        />
        <button type="submit" className="btn-bevel">
          [ Go ]
        </button>
        <ul id={listId} role="listbox" aria-label="Matches" className="search-list" hidden={!showList}>
          {showList && hits.length === 0 && (
            <li role="presentation" className="search-note">
              {q.error ? 'Search is unavailable right now.' : q.loading ? 'Searching…' : 'No matches.'}
            </li>
          )}
          {showList &&
            hits.map((h, i) => (
              <li
                key={`${String(h.kind)}:${String(h.id)}`}
                id={optionId(i)}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'search-hit active' : 'search-hit'}
                onMouseDown={(e) => {
                  e.preventDefault() // keep focus; pick on click
                  pick(h)
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span className="search-kind">{h.kind === 'film' ? 'Film' : 'Person'}</span> {hitLabel(h)}
                {h.kind === 'person' && <span className="search-detail"> {personDetail(h)}</span>}
              </li>
            ))}
        </ul>
      </div>
      <p id={helpId} className="mb-0 mt-1 text-small text-muted">
        Arrow keys pick a match; Enter opens it. Press / to search from anywhere.
      </p>
      <p className="sr-only" role="status">
        {showList && q.rows ? `${films} films and ${people} people found` : ''}
      </p>
    </form>
  )
}
