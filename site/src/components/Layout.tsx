import { Fragment, useId } from 'react'
import { NavLink, Outlet } from 'react-router'
import { formatRetroDate } from '../lib/formatRetroDate'

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/films', label: 'Films' },
  { to: '/leaderboard', label: 'Leaderboard' },
  { to: '/people', label: 'People' },
  { to: '/weekend', label: 'Weekend Charts' },
  { to: '/about', label: 'About' },
]

const BADGES = [
  { file: 'badge-duckdb.svg', alt: 'Powered by DuckDB' },
  { file: 'badge-notepad.svg', alt: 'Made with Notepad' },
  { file: 'badge-wikidata.svg', alt: 'Data: Wikidata' },
  { file: 'badge-any-browser.svg', alt: 'Best viewed in any browser' },
]

const REPO_URL = 'https://github.com/euskali/BoxOfficeBozo'
const NOTICE_URL = `${REPO_URL}/blob/main/DATA_NOTICE.md`

function Sidebar() {
  const searchId = useId()
  const noteId = useId()
  return (
    <aside aria-label="Sidebar" className="flex flex-col gap-3 md:w-[190px] md:shrink-0">
      <section className="box" aria-labelledby="side-search">
        <h2 id="side-search" className="bar m-0 text-body">
          Search
        </h2>
        <form role="search" className="p-2" onSubmit={(e) => e.preventDefault()}>
          <label htmlFor={searchId} className="mb-1 block text-small">
            Search films and people
          </label>
          <div className="flex gap-1">
            <input
              id={searchId}
              type="text"
              name="q"
              autoComplete="off"
              aria-describedby={noteId}
              className="w-full min-w-0 flex-1"
            />
            <button type="submit" className="btn-bevel" aria-label="Go">
              [ Go ]
            </button>
          </div>
          <p id={noteId} className="mb-0 mt-1 text-small text-muted">
            Search arrives later.
          </p>
        </form>
      </section>

      <section className="box" aria-labelledby="side-news">
        <h2 id="side-news" className="bar m-0 text-body">
          Site News
        </h2>
        <ul className="m-0 list-disc py-2 pl-6 pr-2 text-small">
          <li>
            <b>Nov 5 2026:</b> Site scaffolded. Hello 1999!
          </li>
        </ul>
      </section>
    </aside>
  )
}

export default function Layout() {
  const base = import.meta.env.BASE_URL
  return (
    <div className="mx-auto max-w-[980px] px-2 pb-6">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:bg-page focus:p-2"
      >
        Skip to content
      </a>

      <header className="mt-2 border border-edge">
        <div className="bg-row-alt px-3 py-2">
          <div className="font-[Georgia,serif] text-[28px] font-bold leading-tight text-ink">
            BoxOfficeBozo
          </div>
          <div className="text-small text-muted">Box office history, as it happened</div>
        </div>
        <nav aria-label="Main" className="border-t border-edge bg-page px-3 py-1">
          <ul className="m-0 flex list-none flex-wrap p-0">
            {NAV.map((item, i) => (
              <Fragment key={item.to}>
                {i > 0 && (
                  <li aria-hidden="true" className="px-2 text-ink">
                    |
                  </li>
                )}
                <li>
                  <NavLink to={item.to} end={item.end} className="aria-[current=page]:font-bold">
                    {item.label}
                  </NavLink>
                </li>
              </Fragment>
            ))}
          </ul>
        </nav>
      </header>

      <div className="mt-3 flex flex-col gap-3 md:flex-row">
        {/* Sidebar sits after main in the DOM so it collapses under the content on mobile. */}
        <main id="content" tabIndex={-1} className="min-w-0 flex-1 md:order-2">
          <Outlet />
        </main>
        <div className="md:order-1">
          <Sidebar />
        </div>
      </div>

      <footer className="mt-4 border-t-2 border-edge pt-3 text-small">
        <ul className="m-0 mb-3 flex list-none flex-wrap gap-1 p-0">
          {BADGES.map((b) => (
            <li key={b.file}>
              <img src={`${base}img/${b.file}`} width={88} height={31} alt={b.alt} />
            </li>
          ))}
        </ul>
        <p className="m-0 mb-1">
          Last updated: {formatRetroDate(new Date(__BUILD_DATE__))} | You are visitor #000042
          <span className="text-muted"> (static joke counter, nobody is tracked)</span>
        </p>
        <p className="m-0 mb-1">
          Data: Purdue STAT 695 dataset (Box Office Mojo weekend charts) · Internet Archive Wayback
          Machine · Common Crawl · Wikidata (CC0) · BLS CPI · NATO (now Cinema United) and
          Cinema Foundation average ticket prices. Not affiliated with IMDb, Box Office Mojo, or
          The Numbers.
        </p>
        <p className="m-0">
          <a href={NOTICE_URL}>Data Notice</a> | <a href={REPO_URL}>GitHub repo</a>
        </p>
      </footer>
    </div>
  )
}
