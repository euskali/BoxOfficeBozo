import type { ReactNode } from 'react'

/**
 * A wide table's own scroll box: the page never scrolls sideways, the table does. It's focusable
 * so keyboard users can scroll it too.
 */
export default function TableBox({ label, children, maxHeight }: { label: string; children: ReactNode; maxHeight?: number }) {
  return (
    <div
      className="table-box mb-3"
      role="region"
      aria-label={label}
      tabIndex={0}
      style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}
    >
      {children}
    </div>
  )
}
