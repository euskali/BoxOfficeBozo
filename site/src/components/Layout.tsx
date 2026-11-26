import { Fragment, useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { getManifest } from '../db/store'
import { formatRetroDate } from '../lib/formatRetroDate'
import { SOURCES } from '../sources'
import SearchBox from './SearchBox'

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

const BROWSE = [
  { to: '/leaderboard', label: 'All-time leaderboard' },
  { to: '/leaderboard?m=cpi', label: 'Adjusted for inflation' },
  { to: '/leaderboard?m=admissions', label: 'By tickets sold' },
  { to: '/people', label: 'Top directors' },
  { to: '/people?role=actor', label: 'Top actors' },
  { to: '/weekend', label: 'Latest weekend chart' },
  { to: '/films', label: 'Films A to Z' },
]

const NEWS = [
  { date: 'Nov 25 2026', text: 'New data notes on the About page: where every number comes from, on what terms, and what is still rough.' },
  { date: 'Nov 24 2026', text: 'The time machine is open! Leaderboards, film and people pages, and weekend charts for any date since 1982.' },
  { date: 'Nov 5 2026', text: 'Site scaffolded. Hello 1999!' },
]

const REPO_URL = 'https://github.com/euskali/BoxOfficeBozo'
const NOTICE_URL = `${REPO_URL}/blob/main/DATA_NOTICE.md`

function Sidebar({ search }: { search: boolean }) {
  return (
    <aside aria-label="Sidebar" className="flex flex-col gap-3 md:w-[190px] md:shrink-0">
      {search && (
        <section className="box" aria-labelledby="side-search">
          <h2 id="side-search" className="bar m-0 text-body">
            Search
          </h2>
          <div className="p-2">
            <SearchBox />
          </div>
        </section>
      )}

      <section className="box" aria-labelledby="side-browse">
        <h2 id="side-browse" className="bar m-0 text-body">
          Browse
        </h2>
        <ul className="side-list m-0 list-disc py-2 pl-6 pr-2">
          {BROWSE.map((b) => (
            <li key={b.to}>
              <Link to={b.to}>{b.label}</Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="box" aria-labelledby="side-news">
        <h2 id="side-news" className="bar m-0 text-body">
          Site News
        </h2>
        <ul className="m-0 list-disc py-2 pl-6 pr-2 text-small">
          {NEWS.map((n) => (
            <li key={n.date}>
              <b>{n.date}:</b> {n.text}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  )
}

/** A loud box when public/data holds `make sample-data` output instead of real data. */
function SampleBanner() {
  const [sample, setSample] = useState(false)
  useEffect(() => {
    let live = true
    getManifest().then((m) => live && setSample(m?.sample === true))
    return () => {
      live = false
    }
  }, [])
  if (!sample) return null
  return (
    <p className="sample-banner" role="note">
      <b>SAMPLE DATA:</b> these are fictional films with made-up numbers, from <code>make sample-data</code>, for
      local development only. Nothing here is real box office data.
    </p>
  )
}

/** "/" jumps to the search box from anywhere (unless you're typing in a field). */
function useSlashToSearch(): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return
      const box = document.querySelector<HTMLInputElement>('input[data-site-search]')
      if (box) {
        e.preventDefault()
        box.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

export default function Layout() {
  const base = import.meta.env.BASE_URL
  const { pathname } = useLocation()
  useSlashToSearch()
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
        <nav aria-label="Main" className="top-nav border-t border-edge bg-page px-3 py-1">
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
        <main id="content" tabIndex={-1} className="min-h-[85vh] min-w-0 flex-1 md:order-2">
          <SampleBanner />
          <Outlet />
        </main>
        <div className="md:order-1">
          <Sidebar search={pathname !== '/'} />
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
        <p className="m-0 mb-1" data-testid="footer-credits">
          Data:{' '}
          {SOURCES.map((s, i) => (
            <Fragment key={s.id}>
              {i > 0 && ' · '}
              <a href={s.url}>{s.label}</a>
              {s.footer_note && ` (${s.footer_note})`}
            </Fragment>
          ))}
          . Not affiliated with IMDb, Box Office Mojo, or The Numbers.
        </p>
        <p className="m-0">
          <a href={NOTICE_URL}>Data Notice</a> | <a href={REPO_URL}>GitHub repo</a>
        </p>
      </footer>
    </div>
  )
}
