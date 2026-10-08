# dump1090-coverage

[![CI](https://github.com/technothatch/dump1090-coverage/actions/workflows/ci.yml/badge.svg)](https://github.com/technothatch/dump1090-coverage/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/technothatch/dump1090-coverage/blob/main/LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/technothatch/dump1090-coverage)](https://github.com/technothatch/dump1090-coverage/releases)
[![Issues](https://img.shields.io/github/issues/technothatch/dump1090-coverage)](https://github.com/technothatch/dump1090-coverage/issues)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/technothatch/dump1090-coverage/pulls)
[![Code size](https://img.shields.io/github/languages/code-size/technothatch/dump1090-coverage)](https://github.com/technothatch/dump1090-coverage)
[![Last commit](https://img.shields.io/github/last-commit/technothatch/dump1090-coverage)](https://github.com/technothatch/dump1090-coverage/commits/main)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen.svg)](https://github.com/technothatch/dump1090-coverage)

Turn months of recorded [dump1090](https://github.com/flightaware/dump1090) /
[readsb](https://github.com/wiedehopf/readsb) traffic into an answer to the question
every operator eventually asks: *how far does my receiver actually see?* Feed it the
NDJSON export (or the SQLite database) produced by
[dump1090-recorder](https://github.com/technothatch/dump1090-recorder) and it buckets
every position onto a hex grid around the receiver, slices the range into 36 bearing
sectors, and renders a heat map plus the supporting statistics as **one self-contained
HTML file** you can open from a file share with no network at all — GeoJSON for GIS and
a plain-text table for terminals and scripts come out of the same run.

## Features

- **Hex-grid heat map** — unique aircraft per cell (configurable `--cell-km`,
  point-to-point cell width), drawn as inline SVG with range rings, a receiver
  crosshair and hover tooltips. No canvas library, no map tiles, no CDN.
- **Bearing sectors** — 36 × 10° sectors with position count, unique ICAOs,
  p50 / p90 / max range, so a blocked direction or a tall building shows up instantly.
- **Range percentiles** — max / p50 / p90 / p95 over every position, not just the
  single lucky long-haul catch.
- **Traffic statistics** — messages per hour, unique ICAOs per day, altitude
  histogram (with a separate `unknown` bucket), best and worst day.
- **Two inputs, one pipeline** — `dump1090-recorder export --format ndjson` output or
  the recorder's SQLite `positions` table, detected from the file's magic bytes and
  extension (or forced with `--sqlite`).
- **Three outputs** — self-contained `html`, `geojson` (one Polygon per hex cell with
  traffic properties) and `text` (fixed-width ASCII tables, safe on any console).
- **Offline by construction** — zero runtime dependencies, standard library only:
  `math`, `json`, `sqlite3`, `argparse`. No numpy, no matplotlib.

## Install

```bash
pip install dump1090-coverage
```

Or from source:

```bash
git clone https://github.com/technothatch/dump1090-coverage.git
cd dump1090-coverage
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Quickstart

Record some history with [dump1090-recorder](https://github.com/technothatch/dump1090-recorder)
(or point at an existing recording), then summarise it:

```console
$ dump1090-coverage --input flights.ndjson \
    --receiver-lat 51.47 --receiver-lo -0.45 --format text
dump1090-coverage summary
=========================
receiver       51.4700, -0.4500
cell size      5.0 km (2.5 km hex radius)
period         2026-10-01T00:00:00Z .. 2026-10-03T00:00:00Z  (48.0 h)
positions      21 in 13 cells
unique ICAOs   6
skipped rows   1
messages/hour  0.4
range (km)     max 300.0 | p50 60.0 | p90 200.0 | p95 250.0
best day       2026-10-01 (6 ICAOs, 12 positions)
worst day      2026-10-03 (2 ICAOs, 2 positions)

Range by bearing (10-degree sectors)
  sector     count  aircraft    p50 km    p90 km    max km
  000-010        5         3       3.0      20.0      20.0
  010-020        2         2     157.4     271.5     300.0
  ... (34 more sectors, dashes where nothing was heard) ...

Altitude histogram (ft)
  bucket             count
  0-999                  4
  1000-2999              0
  3000-4999              1
  5000-9999              2
  10000-14999            3
  15000-19999            0
  20000-24999            1
  25000-29999            1
  30000-34999            4
  35000-39999            3
  40000+                 1
  unknown                1

Daily activity (UTC)
  day            positions     ICAOs
  2026-10-01            12         6
  2026-10-02             7         6
  2026-10-03             2         2
```

The same run as a heat map you can double-click open:

```console
$ dump1090-coverage --input flights.ndjson \
    --receiver-lat 51.47 --receiver-lo -0.45 --format html --out coverage.html
# 21 positions, 6 aircraft, 13 cells @ 5 km: html -> coverage.html
```

And as GIS input (one hexagon Polygon per cell, properties carry the traffic counts):

```console
$ dump1090-coverage --input flights.ndjson \
    --receiver-lat 51.47 --receiver-lo -0.45 --format geojson --out coverage.geojson
# 21 positions, 6 aircraft, 13 cells @ 5 km: geojson -> coverage.geojson
```

A direct SQLite recording works the same way — the format is detected, so just pass
the database:

```bash
dump1090-coverage --input /var/lib/dump1090-recorder/record.sqlite --format text
```

If the input carries the receiver position (a top-level `lat`/`lon` NDJSON record, or
a `receiver` table in SQLite), the `--receiver-lat` / `--receiver-lo` flags can be
omitted. Everything else is flags; there is no config file.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Input missing/empty/malformed, unknown receiver position, bad `--cell-km`, or output not writable |
| `2` | Command-line usage error |

## Configuration reference

| Flag | Meaning | Default |
| --- | --- | --- |
| `--input PATH` (`-i`) | NDJSON export from `dump1090-recorder export --format ndjson`, or a recorder SQLite database | required |
| `--sqlite` | Treat `--input` as SQLite regardless of magic bytes/extension | off |
| `--receiver-lat DEG` | Receiver latitude in decimal degrees | read from the input |
| `--receiver-lo DEG` | Receiver longitude in decimal degrees | read from the input |
| `--cell-km KM` | Point-to-point width of a hex cell (neighbour centres are `0.866 × cell-km` apart) | `5.0` |
| `--format html\|geojson\|text` | Output format | `html` |
| `--out PATH` | Output file, or `-` for stdout | `-` |
| `--version` | Print version and exit | — |

### Input contract

**NDJSON** — one JSON object per line, `{"t": <epoch seconds>, "aircraft": [ ... ]}`,
the `dump1090-recorder export --format ndjson` convention. Aircraft entries use the
standard `aircraft.json` fields: `hex` (required), `lat`, `lon`, `alt_baro`
(`"ground"` counts as 0 ft, `alt_geom` is the fallback), `flight`. Entries without a
usable position are counted as `skipped rows`, never silently dropped from the
totals.

**SQLite** — a `dump1090-recorder` database with a `positions` table
(`ts, hex, flight, lat, lon, alt_baro, ...`); an optional `receiver` table
(`lat`, `lon`) supplies the receiver position.

## How it works

```
  flights.ndjson / record.sqlite
  ────────────────▶ read.py  ──▶ Observation(t, hex, lat, lon, alt_ft)
   sniff magic,        │          one row per aircraft per snapshot
   parse, validate     │
                       ▼
                  analysis.py  (pure functions, no I/O)
                   ├─ geo.py      haversine, bearing, project(), hex lattice
                   ├─ hex grid    unique aircraft per cell   → heat map
                   ├─ 36 sectors  max / p50 / p90 by bearing → range table
                   ├─ percentiles max / p50 / p90 / p95 overall
                   └─ days, hours, altitude histogram, best/worst day
                       │
                       ▼
                  render.py
                   ├─ html     inline CSS + inline SVG + JSON in <script>
                   ├─ geojson  one Polygon per cell, closed 7-point ring
                   └─ text     fixed-width ASCII tables
```

- **`geo.py` is pure maths** — WGS-84 degrees in, kilometres out. Positions are
  projected onto a local east/north plane centred on the receiver (accurate to well
  under 1% across the few hundred kilometres a receiver can see), bucketed with the
  standard pointy-top axial hex formulas and cube-rounded, so every point belongs to
  exactly one cell.
- **`read.py` normalises everything** — both inputs become `Observation` rows before
  any analysis runs, so the statistics never care where the data came from. All
  failures are `InputError`s with the file name and line number.
- **`analysis.py` aggregates in one pass** — cells, sectors, days and the altitude
  histogram are accumulated while streaming through the rows; percentiles are
  linear-interpolation (the `numpy.percentile` default) with no numpy in sight.
- **`render.py` never reaches the network** — the heat map is SVG polygons built from
  the report, and the whole report is embedded as JSON in the page, so the HTML file
  works from a `file://` URL on a plane.

## Development

```bash
git clone https://github.com/technothatch/dump1090-coverage.git
cd dump1090-coverage
pip install -e ".[dev]"

make lint     # ruff check + ruff format --check + mypy
make test     # pytest with coverage (fail-under 80)
make check    # everything, the same gate CI runs
```

The test suite covers haversine/bearing/hex-grid maths, sector assignment,
percentile edge cases (empty, single value, p=0/p=100, out of range), NDJSON and
SQLite parsing with their error paths, aggregation from the committed fixtures, and
every renderer — including assertions that the HTML embeds its data and references no
`http://`/`https://` resource. 135 tests at 96% line and branch coverage. No test
needs a running decoder.

## Related projects

- [dump1090-fa](https://github.com/flightaware/dump1090) — FlightAware's decoder
- [readsb](https://github.com/wiedehopf/readsb) — high-performance fork, JSON docs in-repo
- [tar1090](https://github.com/wiedehopf/tar1090) — web UI for readsb
- [graphs1090](https://github.com/wiedehopf/graphs1090) — statistics graphs
- [dump1090-recorder](https://github.com/technothatch/dump1090-recorder) — the long-term recorder this reads
- [dump1090-alerts](https://github.com/technothatch/dump1090-alerts) — rule-based notifications
- [squawk-decoder](https://github.com/technothatch/squawk-decoder) — what a squawk code means

## License

MIT © technothatch. See [LICENSE](LICENSE).
