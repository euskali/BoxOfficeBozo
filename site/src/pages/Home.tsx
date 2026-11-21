import SectionBar from '../components/SectionBar'

const MILESTONES = [
  { id: 'M0', name: 'Scaffold', status: 'Done' },
  { id: 'M1', name: 'Ingest 1982–2016', status: 'Done' },
  { id: 'M2', name: 'Ingest 2017 → present', status: 'Done' },
  { id: 'M3', name: 'Identity matching', status: 'Done' },
  { id: 'M4', name: 'Credits & people', status: 'Done' },
  { id: 'M5', name: 'Inflation & admissions', status: 'Coming soon' },
  { id: 'M6', name: 'Ranking engine', status: 'Coming soon' },
  { id: 'M7', name: 'Site', status: 'Coming soon' },
  { id: 'M8', name: 'Data notes & launch', status: 'Coming soon' },
]

const DATA_NOTES = `DATA NOTES
==========
* Rankings will be built in CI from public archives
  and Wikidata, then shipped as static files.
* No numbers are shown yet. Nothing on this page
  is real box office data.
* This is a non-commercial hobby site. It is NOT
  affiliated with IMDb or Box Office Mojo.`

export default function Home() {
  return (
    <>
      <SectionBar>Welcome</SectionBar>
      <h1>Hello 1999</h1>
      <p>
        Welcome, traveler! The BoxOfficeBozo time machine is still under construction. Soon you
        will be able to pick any date and see the all-time box office rankings exactly as they
        stood on that day. Until then, grab a seat and watch the progress below.
      </p>

      <hr />

      <div className="max-h-[26rem] overflow-auto border border-edge">
        <table className="grid-table w-full text-body">
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
      </div>

      <hr />

      <section aria-labelledby="data-notes-h">
        <h2 id="data-notes-h" className="sr-only">
          Data notes
        </h2>
        <pre className="m-0 overflow-x-auto border border-edge bg-row-alt p-3 font-mono text-small leading-snug">
          {DATA_NOTES}
        </pre>
      </section>
    </>
  )
}
