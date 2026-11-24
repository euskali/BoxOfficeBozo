import { Link } from 'react-router'

/** « Previous 100 | 101–200 of 18,565 | Next 100 » */
export default function Pager({
  page,
  pageSize,
  total,
  href,
}: {
  page: number
  pageSize: number
  total: number
  href: (page: number) => string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  const first = (page - 1) * pageSize + 1
  const last = Math.min(total, page * pageSize)
  return (
    <nav aria-label="Pages" className="pager mb-3">
      {page > 1 ? (
        <Link to={href(page - 1)} rel="prev">
          « Previous {pageSize}
        </Link>
      ) : (
        <span className="text-muted">« Previous {pageSize}</span>
      )}
      <span aria-hidden="true"> | </span>
      <span>
        {first.toLocaleString('en-US')}–{last.toLocaleString('en-US')} of {total.toLocaleString('en-US')}
      </span>
      <span aria-hidden="true"> | </span>
      {page < pages ? (
        <Link to={href(page + 1)} rel="next">
          Next {pageSize} »
        </Link>
      ) : (
        <span className="text-muted">Next {pageSize} »</span>
      )}
    </nav>
  )
}
