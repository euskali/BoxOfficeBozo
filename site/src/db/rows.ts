import type { Table } from 'apache-arrow'

export type Value = string | number | boolean | null
export type Row = Record<string, Value>

// Arrow type ids (apache-arrow's Type enum) for the columns that need converting.
const DATE = 8
const TIMESTAMP = 10

/**
 * Plain rows from a DuckDB-WASM result: BIGINT/HUGEINT become numbers (every count and dollar
 * total here is far below 2^53), DATE becomes 'YYYY-MM-DD', and the rest stays as Arrow gives it.
 */
export function toRows(table: Table): Row[] {
  const fields = table.schema.fields
  const out: Row[] = []
  for (const r of table.toArray()) {
    const row: Row = {}
    for (const f of fields) {
      const v: unknown = r[f.name]
      row[f.name] = convert(v, f.type.typeId)
    }
    out.push(row)
  }
  return out
}

function convert(v: unknown, typeId: number): Value {
  if (v === null || v === undefined) return null
  if (typeof v === 'bigint') return Number(v)
  if (typeId === DATE || typeId === TIMESTAMP) {
    const ms = typeof v === 'number' ? v : v instanceof Date ? v.getTime() : Number(v)
    return new Date(ms).toISOString().slice(0, 10)
  }
  if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') return v
  return String(v)
}
