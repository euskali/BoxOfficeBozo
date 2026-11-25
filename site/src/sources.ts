import data from './sources.json'

/** A source the data build uses. See sources.json, which etl/tests/test_sources.py checks against
 * DATA_NOTICE.md, the fetch allowlist and the hand-curated CSVs' citations. */
export interface Source {
  id: string
  name: string
  label: string
  url: string
  terms: string
  gives: string
  /** Shown in brackets after the footer link, e.g. a license. */
  footer_note?: string
}

export const SOURCES: readonly Source[] = data.sources
