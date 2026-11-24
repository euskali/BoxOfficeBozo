import { useEffect, type ReactNode } from 'react'
import { Link } from 'react-router'
import SectionBar from './SectionBar'

export interface Crumb {
  label: string
  to?: string
}

const SITE = 'BoxOfficeBozo'

/** Sets the browser tab's title. */
export function useTitle(title: string | null): void {
  useEffect(() => {
    document.title = title ? `${title} - ${SITE}` : `${SITE}: Box office history, as it happened`
  }, [title])
}

/** Breadcrumbs like "Home > Films > T > Titanic (1997)"; the last crumb is the current page. */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-1 text-small">
      <ol className="crumbs">
        <li>
          <Link to="/">Home</Link>
        </li>
        {items.map((c, i) => (
          <li key={i}>{c.to && i < items.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current="page">{c.label}</span>}</li>
        ))}
      </ol>
    </nav>
  )
}

/**
 * A page's top: section bar, breadcrumbs, the h1 and an intro paragraph. Everything here renders
 * before any data arrives.
 */
export default function PageHead({
  section,
  crumbs,
  title,
  docTitle,
  children,
}: {
  section: string
  crumbs: Crumb[]
  title: ReactNode
  /** The tab title; defaults to `title` when that's a string. */
  docTitle?: string | null
  children?: ReactNode
}) {
  useTitle(docTitle !== undefined ? docTitle : typeof title === 'string' ? title : null)
  return (
    <>
      <SectionBar>{section}</SectionBar>
      <Breadcrumbs items={crumbs} />
      <h1>{title}</h1>
      {children}
    </>
  )
}
