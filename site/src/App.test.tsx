import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { NOTES_WIDTH } from './pages/About'
import { SOURCES } from './sources'

// The pages run the real shared SQL, on the synthetic fixture (src/queries/testdata/fixture.sql),
// through DuckDB-WASM's Node build instead of the browser's lazy loader.
vi.mock('./db/store', async () => {
  const { runFixture } = await import('./test/fixtureDb')
  const idle = { busy: false, done: 0, total: 0, pending: [], tableBytes: 0 }
  return {
    run: runFixture,
    prefetch: () => {},
    ensure: async () => {},
    getManifest: async () => null,
    getProgress: () => idle,
    subscribeProgress: () => () => {},
    ENGINE_TASK: 'the database engine',
  }
})
// uPlot needs a real canvas; jsdom has none.
vi.mock('./components/RankChart', () => ({ default: () => <div data-testid="rank-chart" /> }))

const TIMEOUT = { timeout: 20_000 }

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  )
}

const bodyRows = (table: HTMLElement) => within(table.querySelector('tbody')!).getAllByRole('row')
const cells = (row: HTMLElement) => [...row.querySelectorAll('th, td')].map((c) => c.textContent)

describe('Home', () => {
  it('shows the welcome, the all-time top 10 and a weekend from the past', async () => {
    renderAt('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Box office history, as it happened' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Search films and people' })).toBeInTheDocument()
    const top = await screen.findByRole('table', { name: /All-time top 10 as of Sun Jun 4 1995/ }, TIMEOUT)
    expect(bodyRows(top).map((r) => cells(r).slice(0, 2))).toEqual([
      ['1', 'Test Film Delta'],
      ['2', 'Test Film Bravo'],
      ['3', 'Test Film Alpha'],
      ['3', 'Test Film Charlie'],
      ['5', 'Test Film Echo‡ (includes pre-1982 film rentals, not gross)'],
      ['6', 'Test Film Foxtrot'],
    ])
    expect(await screen.findByRole('table', { name: 'Weekend ending Sun Jun 4 1995' }, TIMEOUT)).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Last updated:')
  })
})

describe('Leaderboard', () => {
  it('ranks on the date, compares with a year before and links the other measures', async () => {
    renderAt('/leaderboard?date=1991-01-13')
    const table = await screen.findByRole('table', { name: /All-time leaderboard as of Sun Jan 13 1991/ }, TIMEOUT)
    const rows = bodyRows(table).map((r) => cells(r).slice(0, 3))
    expect(rows).toEqual([
      ['1', 'NEW on the list', 'Test Film Bravo'],
      ['2', '–no change', 'Test Film Alpha'],
      ['2', 'NEW on the list', 'Test Film Charlie'],
      ['4', '▼3 places down', 'Test Film Echo‡ (includes pre-1982 film rentals, not gross)'],
    ])
    const measures = screen.getByRole('navigation', { name: 'Measure' })
    expect(within(measures).getByRole('link', { name: 'Est. tickets' })).toHaveAttribute('href', '/leaderboard?date=1991-01-13&m=admissions')
    // the table's column headers sort by the other measures too
    expect(within(table).getByRole('link', { name: 'Est. tickets' })).toHaveAttribute('href', '/leaderboard?date=1991-01-13&m=admissions')
    expect(screen.getByText(/Includes a pre-1982 total of film rentals/)).toBeInTheDocument()
  })
})

describe('Film page', () => {
  it('shows the facts, the rank on the date with its neighbours, and every weekend', async () => {
    renderAt('/film/test_alpha?date=1991-01-13')
    expect(await screen.findByRole('heading', { level: 1, name: 'Test Film Alpha (1990)' }, TIMEOUT)).toBeInTheDocument()
    expect(await screen.findByText(/ranked/, { selector: 'p' }, TIMEOUT)).toHaveTextContent(
      'On Sun Jan 13 1991, Test Film Alpha ranked 2nd of all time by box office gross in the dollars of the day, with $300.',
    )
    const slice = await screen.findByRole('table', { name: /The all-time list around this film/ }, TIMEOUT)
    const current = bodyRows(slice).find((r) => r.getAttribute('aria-current') === 'true')!
    expect(cells(current)).toEqual(['2', 'Test Film Alpha', '1990', '$300'])
    const weekends = await screen.findByRole('table', { name: 'Every weekend chart the film appeared on' }, TIMEOUT)
    expect(bodyRows(weekends).map((r) => cells(r))).toEqual([
      ['Jan 7 1990', '1', '$100', '–', '10', '$100', '1'],
      ['Jan 14 1990', '1', '$200', '+100.0%', '12', '$300', '2'],
    ])
    expect(screen.getByTestId('rank-chart')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Test Director One' })).toHaveAttribute('href', '/person/P1')
  })

  it('says when a film is not in the data', async () => {
    renderAt('/film/no_such_title')
    expect(await screen.findByRole('heading', { level: 1, name: 'Film not found' }, TIMEOUT)).toBeInTheDocument()
  })
})

describe('Person page', () => {
  it('ranks the career total on the date and marks credits that do not count', async () => {
    renderAt('/person/P10?date=1995-06-04')
    expect(await screen.findByRole('heading', { level: 1, name: 'Test Actor Ten' }, TIMEOUT)).toBeInTheDocument()
    const career = await screen.findByRole('table', { name: /Career totals/ }, TIMEOUT)
    await waitFor(() => expect(cells(bodyRows(career)[0]!)[3]).toMatch(/^1st of 3 actors on Sun Jun 4 1995/), TIMEOUT)
    expect(cells(bodyRows(career)[0]!).slice(0, 3)).toEqual(['Actor (top 4 billed)', '2', '$1,300'])
    const films = await screen.findByRole('table', { name: /^Films, with each film/ }, TIMEOUT)
    expect(bodyRows(films).map((r) => cells(r))).toEqual([
      ['1990', 'Test Film Alpha', 'Actor, billed 1st', '$300', '3'],
      ['1991', 'Test Film Bravo', 'Actor, billed 5th (not counted)', '$400', '2'],
      ['1995', 'Test Film Delta', 'Actor, billed 4th', '$1,000', '1'],
    ])
  })
})

describe('Weekend chart', () => {
  it('snaps back to the weekend, with last week and the change', async () => {
    renderAt('/weekend?date=1991-01-16')
    expect(await screen.findByRole('heading', { level: 1, name: 'Weekend box office: Sun Jan 13 1991' }, TIMEOUT)).toBeInTheDocument()
    const table = screen.getByRole('table', { name: /Weekend box office chart/ })
    expect(bodyRows(table).map((r) => cells(r))).toEqual([
      ['1', '2', 'Test Film Charlie', 'Fictional Pictures', '$250', '+400.0%', '25', '$300', '2'],
      ['2', '1', 'Test Film Bravo', 'Imaginary Films', '$200', '0.0%', '20', '$400', '2'],
    ])
    expect(screen.getByRole('link', { name: '‹ Previous weekend' })).toHaveAttribute('href', '/weekend?date=1991-01-06')
    expect(screen.getByRole('link', { name: 'Next weekend ›' })).toHaveAttribute('href', '/weekend?date=1995-06-04')
  })
})

describe('Browse and search', () => {
  it('lists films by letter', async () => {
    renderAt('/films?letter=G')
    const table = await screen.findByRole('table', { name: 'Films under G' }, TIMEOUT)
    expect(bodyRows(table).map((r) => cells(r))).toEqual([['The Golf Picture', '1996', '–', 'not charted']])
  })

  it('finds films and people from the box, by keyboard', async () => {
    const user = userEvent.setup()
    renderAt('/about')
    const box = screen.getByRole('combobox', { name: 'Search films and people' })
    await user.type(box, 'director')
    const options = await screen.findAllByRole('option', {}, TIMEOUT)
    expect(options.map((o) => o.textContent)).toEqual([
      'Person Test Director One director of 3 films',
      'Person Test Director Two director of 2 films',
      'Person Test Director Three director of 1 film',
    ])
    await user.keyboard('{ArrowDown}{ArrowDown}')
    expect(box).toHaveAttribute('aria-activedescendant', options[1]!.id)
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('heading', { level: 1, name: 'Test Director Two' }, TIMEOUT)).toBeInTheDocument()
  })

  it('has a full results page', async () => {
    renderAt('/search?q=golf')
    expect(await screen.findByRole('link', { name: 'The Golf Picture' }, TIMEOUT)).toHaveAttribute('href', '/film/test_golf')
  })
})

describe('Static pages', () => {
  it('shows the data notes and the 9-row construction table on About', () => {
    renderAt('/about')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('About BoxOfficeBozo')
    expect(bodyRows(screen.getByRole('table', { name: 'Construction progress' }))).toHaveLength(9)
  })

  it('answers every data question M8 asks for, in lines that fit a phone', () => {
    renderAt('/about')
    const notes = document.querySelector('pre.notes')!.textContent!
    for (const q of [
      'Where do the numbers come from, and on what terms?',
      'What does "domestic" mean?',
      'Are these final figures or estimates?',
      'How do baselines work?',
      'Why do CPI dollars and tickets rank films',
      'What about re-releases?',
      "What's still missing or rough?",
      'I found a mistake, or want something removed.',
    ]) {
      expect(notes).toContain(`Q: ${q}`)
    }
    const widest = Math.max(...notes.split('\n').map((l) => l.length))
    expect(widest).toBeLessThanOrEqual(NOTES_WIDTH)
  })

  it('lists every source on About and links each one in the footer', () => {
    renderAt('/about')
    const notes = document.querySelector('pre.notes')!.textContent!.replace(/\s+/g, ' ')
    const credits = screen.getByTestId('footer-credits')
    expect(within(credits).getAllByRole('link')).toHaveLength(SOURCES.length)
    for (const s of SOURCES) {
      expect(notes).toContain(`* ${s.label}: ${s.gives} Terms: ${s.terms}.`)
      expect(within(credits).getByRole('link', { name: s.label })).toHaveAttribute('href', s.url)
    }
  })

  it('renders the 404 page for unknown routes', () => {
    renderAt('/no/such/page')
    expect(screen.getByRole('heading', { level: 1, name: /404/ })).toBeInTheDocument()
  })
})
