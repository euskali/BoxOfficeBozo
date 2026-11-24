import { Link } from 'react-router'
import { str } from '../components/Cells'
import ErrorBox from '../components/ErrorBox'
import LoadingBox from '../components/LoadingBox'
import PageHead from '../components/PageHead'
import { hitHref, personDetail } from '../components/SearchBox'
import SectionBar from '../components/SectionBar'
import { useQuery } from '../db/useQuery'
import { useView } from '../lib/view'
import { search } from '../queries'

const LIMIT = 50

export default function Search() {
  const { params } = useView()
  const text = (params.get('q') ?? '').trim()
  const q = useQuery(text ? search({ text, limit: LIMIT }) : null)
  const films = q.rows?.filter((r) => r.kind === 'film') ?? []
  const people = q.rows?.filter((r) => r.kind === 'person') ?? []

  return (
    <>
      <PageHead section="Search" crumbs={[{ label: 'Search' }]} title={text ? `Search: ${text}` : 'Search'}>
        <p>
          Films and people whose names have a word starting with what you typed. Punctuation, accents and
          capitals don&rsquo;t matter, so &ldquo;et&rdquo; finds E.T. and &ldquo;amelie&rdquo; finds Amélie. Films
          are listed biggest first; people by how many films they&rsquo;re credited on.
        </p>
      </PageHead>
      {!text && <p>Type a film or a name into the search box.</p>}
      {q.error && <ErrorBox error={q.error} />}
      {text && !q.rows && !q.error && <LoadingBox what="search" minHeight={300} />}
      {text && q.rows && (
        <>
          <SectionBar>{`Films (${films.length}${films.length === LIMIT ? '+' : ''})`}</SectionBar>
          {films.length ? (
            <ul className="hit-list">
              {films.map((h) => (
                <li key={String(h.id)}>
                  <Link to={hitHref(h)}>{String(h.name)}</Link> ({String(h.year ?? '?')})
                  {str(h.detail) && <span className="text-muted"> · {str(h.detail)}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p>No films match.</p>
          )}
          <SectionBar>{`People (${people.length}${people.length === LIMIT ? '+' : ''})`}</SectionBar>
          {people.length ? (
            <ul className="hit-list">
              {people.map((h) => (
                <li key={String(h.id)}>
                  <Link to={hitHref(h)}>{String(h.name)}</Link>
                  <span className="text-muted"> · {personDetail(h)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No people match.</p>
          )}
        </>
      )}
    </>
  )
}
