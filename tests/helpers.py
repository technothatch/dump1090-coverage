"""Helpers for building inputs: NDJSON lines and dump1090-recorder SQLite databases."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_NDJSON = FIXTURES / "sample.ndjson"
RECEIVER_HINT_NDJSON = FIXTURES / "receiver_hint.ndjson"

#: Receiver used by every fixture: 51.47 N, 0.45 W.
RECEIVER_LAT = 51.47
RECEIVER_LON = -0.45

POSITIONS_SCHEMA = """
CREATE TABLE positions (
    ts REAL,
    hex TEXT,
    flight TEXT,
    lat REAL,
    lon REAL,
    alt_baro TEXT,
    gs REAL,
    track REAL,
    squawk TEXT,
    rssi REAL,
    seen_pos REAL,
    raw_json TEXT
);
"""


def write_ndjson(path: Path, records: list[dict[str, object]]) -> Path:
    """Write one JSON object per line, exactly like ``dump1090-recorder export``."""
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_sqlite(
    path: Path,
    rows: list[tuple[object, ...]],
    *,
    receiver: tuple[float, float] | None = None,
) -> Path:
    """Create a ``dump1090-recorder`` database with a ``positions`` table."""
    connection = sqlite3.connect(path)
    with connection:
        connection.executescript(POSITIONS_SCHEMA)
        connection.executemany(
            "INSERT INTO positions (ts, hex, flight, lat, lon, alt_baro) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        if receiver is not None:
            connection.execute("CREATE TABLE receiver (ts REAL, lat REAL, lon REAL)")
            connection.execute(
                "INSERT INTO receiver (ts, lat, lon) VALUES (?, ?, ?)",
                (0.0, receiver[0], receiver[1]),
            )
    connection.close()
    return path
