// DuckDB-WASM reads Parquet through an extension it downloads at runtime, by default from
// extensions.duckdb.org. To keep visitors' browsers off third-party servers, the site serves the
// extension itself: this downloads DuckDB's official builds for the pinned engine
// (src/queries/engine.json) into public/duckdb-extensions/<engine>/<platform>/, checks each against
// its pinned SHA-256, and src/db/duckdb.ts points DuckDB there. Files already in place with the
// right checksum aren't downloaded again. The folder is gitignored, like other build outputs.
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const site = join(dirname(fileURLToPath(import.meta.url)), '..')
const pins = JSON.parse(readFileSync(join(site, 'src', 'queries', 'engine.json'), 'utf8'))
const REPOSITORY = 'https://extensions.duckdb.org'
const out = join(site, 'public', 'duckdb-extensions', pins.engine)

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex')

let failed = false
for (const [name, builds] of Object.entries(pins.extensions)) {
  if (name === 'note') continue
  for (const [platform, expected] of Object.entries(builds)) {
    const file = join(out, platform, `${name}.duckdb_extension.wasm`)
    if (existsSync(file) && sha256(readFileSync(file)) === expected) {
      console.log(`duckdb-extensions: ${platform}/${name} ok`)
      continue
    }
    const url = `${REPOSITORY}/${pins.engine}/${platform}/${name}.duckdb_extension.wasm`
    const res = await fetch(url, { headers: { 'User-Agent': 'BoxOfficeBozo-site-build (+https://github.com/euskali/BoxOfficeBozo)' } })
    if (!res.ok) {
      console.error(`duckdb-extensions: ${url}: HTTP ${res.status}`)
      failed = true
      continue
    }
    const body = Buffer.from(await res.arrayBuffer())
    const got = sha256(body)
    if (got !== expected) {
      console.error(`duckdb-extensions: ${url}: SHA-256 ${got}, expected ${expected} (engine.json)`)
      failed = true
      continue
    }
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, body)
    console.log(`duckdb-extensions: ${platform}/${name} downloaded (${body.length} bytes)`)
  }
}
if (failed) process.exit(1)
