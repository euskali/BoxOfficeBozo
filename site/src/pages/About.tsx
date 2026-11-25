import PageHead from '../components/PageHead'
import SectionBar from '../components/SectionBar'
import TableBox from '../components/TableBox'
import { TOP_BILLED } from '../queries'

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
  { id: 'M8', name: 'Data notes & launch', status: 'Coming soon' },
]

const FAQ = `BOXOFFICEBOZO DATA NOTES
========================

Q: What is this?
A: A free, non-commercial hobby site of domestic (US and
   Canada) box office history. Pick any date since 1982
   and see the all-time lists as they stood that day.

Q: Where do the numbers come from?
A: * Weekend charts 1982-2016: the Purdue STAT 695
     dataset, Box Office Mojo's charts as compiled in
     March 2017 (an MIT-licensed R package).
   * Weekend charts 2017 on: archived copies of Box
     Office Mojo's weekend charts, from the Internet
     Archive's Wayback Machine and Common Crawl. We never
     fetch Box Office Mojo or IMDb themselves.
   * Films, directors and cast: Wikidata (CC0).
   * Inflation: the BLS consumer price index (CPI-U).
   * Average ticket prices: NATO (now Cinema United) and
     the Cinema Foundation, each row cited.

Q: What do the three measures mean?
A: NOMINAL $     Gross in the dollars of the day.
   CPI-ADJ. $    Each weekend's gross deflated by that
                 month's CPI-U, shown in today's dollars
                 (or the chosen date's).
   EST. TICKETS  Each weekend's gross divided by that
                 year's average ticket price. Years with
                 no published price are interpolated.

Q: Why is an older film missing, or so low?
A: Our weekend charts begin in January 1982. A film
   released before then counts only its later runs,
   unless we have a sourced total from before 1982
   (marked with a dagger). Only a few are sourced so
   far; more are coming.

Q: What about re-releases?
A: Re-issues and special editions add to the film's
   lifetime total, as Box Office Mojo did it. Each film
   page lists its releases and every weekend it charted.

Q: How are career totals worked out?
A: A director's total adds up every film they directed.
   An actor's adds up the films they were billed in the
   top ${TOP_BILLED} of, by Wikidata's cast order.

Q: What does the "e" mean?
A: The archived chart we read still showed the studios'
   Sunday estimate for that weekend, not the final
   actual figure.

Q: I found a mistake, or want something removed.
A: Please open a "Takedown or correction request" issue
   on GitHub (link below). The Data Notice lists each
   source's terms.`

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
