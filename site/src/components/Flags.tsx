/**
 * Footnote marks that keep the data's caveats on screen (CLAUDE.md: rentals aren't grosses, and
 * the baseline and estimate flags go all the way to the UI). Each mark has screen-reader text;
 * FlagLegend explains the marks a table uses.
 */

/** † a total that includes a pre-1982 gross; ‡ one that includes pre-1982 film rentals. */
export function BaselineMark({ baseline, rental }: { baseline: unknown; rental: unknown }) {
  if (baseline !== true) return null
  const isRental = rental === true
  return (
    <sup className="flag">
      <span aria-hidden="true">{isRental ? '‡' : '†'}</span>
      <span className="sr-only">
        {isRental ? ' (includes pre-1982 film rentals, not gross)' : ' (includes a pre-1982 total)'}
      </span>
    </sup>
  )
}

/** e: an estimated weekend figure, not an actual. */
export function EstimateMark({ estimate }: { estimate: unknown }) {
  if (estimate !== true) return null
  return (
    <sup className="flag">
      <span aria-hidden="true">e</span>
      <span className="sr-only"> (estimate)</span>
    </sup>
  )
}

export function FlagLegend({ baseline, rental, estimate }: { baseline?: boolean; rental?: boolean; estimate?: boolean }) {
  if (!baseline && !rental && !estimate) return null
  return (
    <ul className="legend">
      {baseline && (
        <li>
          <span aria-hidden="true">†</span> Includes the film&rsquo;s total before 1982, from an archived Box Office Mojo
          page (our weekend charts start in 1982).
        </li>
      )}
      {rental && (
        <li>
          <span aria-hidden="true">‡</span> Includes a pre-1982 total of film rentals (the studio&rsquo;s share), not box
          office gross.
        </li>
      )}
      {estimate && (
        <li>
          <span aria-hidden="true">e</span> Estimate: the archived chart we read still showed the studios&rsquo; Sunday
          estimate, not the final actual figure.
        </li>
      )}
    </ul>
  )
}
