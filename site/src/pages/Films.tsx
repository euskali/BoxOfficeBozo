import { FilmLink, num, str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import LetterBar, { LETTERS } from '../components/LetterBar'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import Pager from '../components/Pager'
import TableBox from '../components/TableBox'
import { useQuery } from '../db/useQuery'
import { money } from '../lib/format'
import { useView } from '../lib/view'
import { browseFilms } from '../queries'

const PAGE_SIZE = 100

export default function Films() {
  const { params, link } = useView()
  const raw = (params.get('letter') ?? '').toUpperCase()
  const letter = (LETTERS as readonly string[]).includes(raw) ? raw : null
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1)
  const q = useQuery(letter ? browseFilms({ letter, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }) : null)
  const rows = q.rows
  const total = num(rows?.[0]?.matching) ?? 0

  return (
    <>
      <PageHead
        section="Films"
        crumbs={[{ label: 'Films', to: '/films' }, ...(letter ? [{ label: letter }] : [])]}
        title={letter ? `Films: ${letter === '#' ? 'numbers and symbols' : letter}` : 'Films A to Z'}
      >
        <p>
          Every film in our weekend charts since 1982, plus the major older films whose earlier totals we
          have sourced. Titles file under their first word, skipping a leading &ldquo;The&rdquo;, &ldquo;A&rdquo; or
          &ldquo;An&rdquo;. Pick a letter, or use the search box to jump straight to a film.
        </p>
      </PageHead>
      <LetterBar current={letter} />

      {!letter && <p>Pick a letter above to list its films, with each film&rsquo;s latest total gross.</p>}
      {q.error && <ErrorBox error={q.error} />}
      {letter && !rows && !q.error && <LoadingBox what={`films under ${letter}`} minHeight={600} />}
      {letter && rows && (
        rows.length === 0 ? (
          <p>No films under {letter}.</p>
        ) : (
          <>
            <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
            <TableBox label={`Films under ${letter}`}>
              <table className="grid-table w-full">
                <caption className="sr-only">Films under {letter}</caption>
                <thead>
                  <tr>
                    <th scope="col">Title</th>
                    <th scope="col" className="num">
                      Year
                    </th>
                    <th scope="col">Distributor</th>
                    <th scope="col" className="num">
                      Total gross
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={String(r.title_id)}>
                      <th scope="row">
                        <FilmLink id={r.title_id} title={r.title} />
                      </th>
                      <td className="num">{num(r.year)}</td>
                      <td>{str(r.distributor) ?? '–'}</td>
                      <td className="num">{num(r.gross) === null ? 'not charted' : money(num(r.gross)!)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBox>
            <Pager page={page} pageSize={PAGE_SIZE} total={total} href={(p) => link({ page: p === 1 ? null : p })} />
          </>
        )
      )}
    </>
  )
}
