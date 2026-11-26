import PageHead from '../components/PageHead'
import SectionBar from '../components/SectionBar'
import TableBox from '../components/TableBox'
import { TOP_BILLED } from '../queries'
import { SOURCES } from '../sources'

const REPO_URL = 'https://github.com/euskali/BoxOfficeBozo'

export const MILESTONES = [
  { id: 'M0', name: 'Scaffold', status: 'Done' },
  { id: 'M1', name: 'Ingest 1982–2016', status: 'Done' },
  { id: 'M2', name: 'Ingest 2017 → present', status: 'Done' },
  { id: 'M3', name: 'Identity matching', status: 'Done' },
  { id: 'M4', name: 'Credits & people', status: 'Done' },
  { id: 'M5', name: 'Inflation & admissions', status: 'Done' },
  { id: 'M6', name: 'Ranking engine', status: 'Done' },
  { id: 'M7', name: 'Site', status: 'Done' },
  { id: 'M8', name: 'Data notes & launch', status: 'Done' },
]

/** The FAQ's widest line, so it fits a 375 px phone in the .notes box. */
export const NOTES_WIDTH = 56

/** Word-wrap `text` to NOTES_WIDTH: the first line starts with `first`, the rest with `rest`. */
export function wrap(text: string, first: string, rest: string): string {
  const lines: string[] = []
  let line = first
  let empty = true
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (!empty && line.length + 1 + word.length > NOTES_WIDTH) {
      lines.push(line)
      line = rest + word
    } else {
      line += (empty ? '' : ' ') + word
    }
    empty = false
  }
  lines.push(line)
  return lines.join('\n')
}

const SOURCE_NOTES = SOURCES.map((s) => wrap(`${s.label}: ${s.gives} Terms: ${s.terms}.`, '   * ', '     ')).join('\n')

export const FAQ = `BOXOFFICEBOZO DATA NOTES
========================

Q: What is this?
A: A free, non-commercial hobby site of domestic box
   office history. Pick any date since 1982 and see
   the all-time lists as they stood that day.

Q: What does "domestic" mean?
A: The United States and Canada together, as the
   weekend charts count it. Worldwide grosses aren't
   covered.

Q: Where do the numbers come from, and on what terms?
A: Nearly every box office figure is Box Office Mojo's,
   read from copies of its charts. We never fetch Box
   Office Mojo, IMDb or The Numbers themselves, and we
   publish figures and our own sums, not their pages.
   Every source the site uses:
${SOURCE_NOTES}
   The Data Notice (link below) sets out each one's
   terms.

Q: Are these final figures or estimates?
A: Studios report a weekend's gross as an estimate on
   Sunday and the actual figure on Monday. From 2017
   we read an archived chart captured more than a week
   after the weekend, when it shows actuals. Where the
   archive only kept the Sunday estimate, the figure
   is marked "e". The 1982-2016 charts are as Box
   Office Mojo had them in March 2017.

Q: What do the three measures mean?
A: NOMINAL $     Gross in the dollars of the day.
   CPI-ADJ. $    Each weekend's gross deflated by that
                 month's CPI-U, shown in today's dollars
                 (or the chosen date's).
   EST. TICKETS  Each weekend's gross divided by that
                 year's average ticket price. Years with
                 no published price are interpolated.

Q: Why do CPI dollars and tickets rank films
   differently?
A: CPI-U follows consumer prices in general; tickets
   follow what a cinema seat cost that year. Where the
   two moved apart, the lists differ. Both are our own
   estimates, not official figures.

Q: Why is an older film missing, or so low?
A: Our weekend charts begin in January 1982. A film
   released before then counts only its runs from
   1982 on, unless we have a sourced total for its
   earlier runs: a baseline, marked with a dagger.

Q: How do baselines work?
A: A baseline is a film's domestic gross before 1982,
   copied from an archived Box Office Mojo release
   summary and cited. It counts from January 1, 1982,
   and the charts from then on add to it. Rentals
   (what distributors got back, which old trade
   papers reported) are flagged and never mixed with
   grosses. A baseline's tickets come from Box Office
   Mojo's published estimate of its tickets where
   there is one, else from its release year's average
   price. Only a few films have a baseline so far;
   more are coming.

Q: What about re-releases?
A: Re-issues, anniversary runs and special editions
   add to the film's lifetime total, as Box Office
   Mojo counts them. We spot them by their chart
   titles (words like "Re-issue" or "Special
   Edition", or a 3D or IMAX tag) or by Box Office
   Mojo's own re-release label, and group the rest by
   hand, each with a citation. Each film page lists
   its releases and every weekend it charted.

Q: How are career totals worked out?
A: A director's total adds up every film they
   directed. An actor's adds up the films they were
   billed in the top ${TOP_BILLED} of, by Wikidata's cast order.

Q: What's still missing or rough?
A: * Films released before 1982 without a baseline
     count only their later runs.
   * Some re-issues of pre-1982 films aren't joined to
     their film yet, so they show as films of their
     own.
   * Years with no published average ticket price are
     interpolated, and years after the latest
     published one reuse its price, so recent ticket
     counts run high if prices rose.
   * The latest weekends use the latest CPI month BLS
     has published, until the next one is out. A
     month BLS never published is filled in between
     its neighbours.
   * Many 1982-2016 chart rows have no theater count;
     the tables show a dash.
   * Box Office Mojo's own running totals sometimes go
     down from one weekend to the next. We keep them
     as charted and flag them in our checks.
   * Cast lists come from Wikidata and can be
     incomplete; billing follows Wikidata's order.
   * Some releases, mostly small ones, couldn't be
     matched to a Wikidata film; they keep a page of
     their own.

Q: I found a mistake, or want something removed.
A: Please open a "Takedown or correction request"
   issue on GitHub (link below), or reach the
   maintainer through their GitHub profile. Accepted
   takedowns are left out of the next build.`

export default function About() {
  return (
    <>
      <PageHead section="About" crumbs={[{ label: 'About' }]} title="About BoxOfficeBozo and its data">
        <p>
          BoxOfficeBozo is a free hobby site, made by someone who loves box office charts. It isn&rsquo;t
          affiliated with IMDb, Box Office Mojo or The Numbers. Here&rsquo;s where the numbers come from, what
          the three measures mean, and what&rsquo;s still missing.
        </p>
      </PageHead>

      <pre className="notes">{FAQ}</pre>

      <p>
        Read the full <a href={`${REPO_URL}/blob/main/DATA_NOTICE.md`}>Data Notice</a>, the{' '}
        <a href={`${REPO_URL}/blob/main/docs/DATA_SOURCES.md`}>data sources</a>, or{' '}
        <a href={`${REPO_URL}/issues/new?template=takedown.md`}>report a problem</a>.
      </p>

      <SectionBar>Construction progress</SectionBar>
      <TableBox label="Construction progress">
        <table className="grid-table w-full">
          <caption>Construction progress</caption>
          <thead>
            <tr>
              <th scope="col">Milestone</th>
              <th scope="col">Name</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {MILESTONES.map((m) => (
              <tr key={m.id}>
                <th scope="row">{m.id}</th>
                <td>{m.name}</td>
                <td>{m.status === 'Done' ? <b>✓ Done</b> : m.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableBox>
    </>
  )
}
