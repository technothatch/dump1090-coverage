"""Input readers: NDJSON snapshots and ``dump1090-recorder`` SQLite databases.

Both supported sources are normalised into :class:`dump1090_coverage.models.Observation`
rows before analysis:

* **NDJSON** — one JSON object per line, ``{"t": <epoch>, "aircraft": [...]}``,
  the convention used by ``dump1090-recorder export --format ndjson``. A record
  carrying a top-level ``lat``/``lon`` (or a ``{"lat": ..., "lon": ...}``
  ``receiver`` object) is treated as receiver metadata instead of traffic.
* **SQLite** — a ``dump1090-recorder`` database with a ``positions`` table
  (``ts, hex, flight, lat, lon, alt_baro, ...``), optionally a ``receiver`` table
  holding the receiver's ``lat``/``lon``.

The format is detected from the ``--sqlite`` flag, the file's magic bytes and
its extension — in that order.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dump1090_coverage.errors import InputError
from dump1090_coverage.models import Observation

__all__ = ["SQLITE_MAGIC", "Dataset", "detect_format", "load"]

#: First bytes of every SQLite database file.
SQLITE_MAGIC = b"SQLite format 3\x00"

#: Extensions that imply a SQLite database even when the magic check is skipped.
SQLITE_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".db", ".db3"})

#: How a recording was read.
SourceFormat = Literal["ndjson", "sqlite"]


@dataclass(frozen=True, slots=True)
class Dataset:
    """A loaded recording: observations plus what we learned about the source."""

    observations: list[Observation]
    receiver: tuple[float, float] | None
    skipped: int
    source: SourceFormat
    path: Path

    @property
    def start(self) -> float:
        """Epoch seconds of the earliest observation (0.0 when empty)."""
        return min((obs.t for obs in self.observations), default=0.0)

    @property
    def end(self) -> float:
        """Epoch seconds of the latest observation (0.0 when empty)."""
        return max((obs.t for obs in self.observations), default=0.0)


def _number(value: object) -> float | None:
    """Coerce a JSON/SQLite value to a finite ``float``; ``None`` otherwise.

    ``bool`` is rejected even though it subclasses ``int``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _altitude(entry: Mapping[str, Any]) -> float | None:
    """Feet for ``alt_baro`` (``"ground"`` becomes 0 ft), falling back to ``alt_geom``."""
    if entry.get("alt_baro") == "ground":
        return 0.0
    alt = _number(entry.get("alt_baro"))
    if alt is None:
        alt = _number(entry.get("alt_geom"))
    return alt


def _receiver_pair(record: Mapping[str, Any]) -> tuple[float, float] | None:
    """Receiver ``lat``/``lon`` from a record, or ``None`` when absent/unusable."""
    lat = _number(record.get("lat"))
    lon = _number(record.get("lon"))
    if lat is None or lon is None:
        nested = record.get("receiver")
        if isinstance(nested, Mapping):
            lat = _number(nested.get("lat"))
            lon = _number(nested.get("lon"))
    if lat is None or lon is None:
        return None
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None
    return lat, lon


def _observation(t: float, entry: Mapping[str, Any]) -> Observation | None:
    """Build an observation from one aircraft object; ``None`` if it has no usable position."""
    hex_id = entry.get("hex")
    if not isinstance(hex_id, str) or not hex_id.strip():
        return None
    lat = _number(entry.get("lat"))
    lon = _number(entry.get("lon"))
    if lat is None or lon is None:
        return None
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None
    flight = entry.get("flight")
    callsign = flight.strip() if isinstance(flight, str) and flight.strip() else None
    return Observation(
        t=t,
        hex=hex_id.strip().lower(),
        lat=lat,
        lon=lon,
        alt_ft=_altitude(entry),
        flight=callsign,
    )


def detect_format(path: Path, *, force_sqlite: bool = False) -> SourceFormat:
    """Decide how to read ``path``: ``--sqlite`` flag, magic bytes, then extension."""
    if force_sqlite:
        return "sqlite"
    try:
        with path.open("rb") as handle:
            head = handle.read(len(SQLITE_MAGIC))
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise InputError(f"cannot read {path}: {reason}") from exc
    if head.startswith(SQLITE_MAGIC):
        return "sqlite"
    if path.suffix.lower() in SQLITE_SUFFIXES:
        return "sqlite"
    return "ndjson"


def _load_ndjson(path: Path) -> Dataset:
    """Read a ``dump1090-recorder`` NDJSON export line by line."""
    observations: list[Observation] = []
    receiver: tuple[float, float] | None = None
    skipped = 0
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise InputError(f"cannot read {path}: {reason}") from exc
    with handle:
        try:
            for lineno, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise InputError(f"{path.name}:{lineno}: invalid JSON ({exc.msg})") from exc
                if not isinstance(record, dict):
                    raise InputError(f"{path.name}:{lineno}: expected a JSON object per line")
                pair = _receiver_pair(record)
                if pair is not None:
                    receiver = pair
                if "t" not in record and "aircraft" not in record:
                    if pair is None:
                        raise InputError(
                            f"{path.name}:{lineno}: record has neither 't'/'aircraft' "
                            "nor receiver 'lat'/'lon'"
                        )
                    continue
                t = _number(record.get("t"))
                aircraft = record.get("aircraft")
                if t is None or not isinstance(aircraft, list):
                    raise InputError(
                        f"{path.name}:{lineno}: record needs a numeric 't' and an 'aircraft' array"
                    )
                for entry in aircraft:
                    if not isinstance(entry, dict):
                        skipped += 1
                        continue
                    observation = _observation(t, entry)
                    if observation is None:
                        skipped += 1
                    else:
                        observations.append(observation)
        except UnicodeDecodeError as exc:
            raise InputError(f"{path.name}: not valid UTF-8 text ({exc})") from exc
    return Dataset(
        observations=observations,
        receiver=receiver,
        skipped=skipped,
        source="ndjson",
        path=path,
    )


def _receiver_from_db(
    connection: sqlite3.Connection, tables: set[str]
) -> tuple[float, float] | None:
    """Receiver position from an optional ``receiver`` table, or ``None``."""
    if "receiver" not in tables:
        return None
    columns = {row[1] for row in connection.execute("PRAGMA table_info(receiver)")}
    if not {"lat", "lon"} <= columns:
        return None
    row = connection.execute('SELECT "lat", "lon" FROM "receiver" LIMIT 1').fetchone()
    if row is None:
        return None
    lat = _number(row[0])
    lon = _number(row[1])
    if lat is None or lon is None:
        return None
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None
    return lat, lon


def _load_sqlite(path: Path) -> Dataset:
    """Read the ``positions`` table of a ``dump1090-recorder`` database."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise InputError(f"{path.name}: cannot open SQLite database ({exc})") from exc
    try:
        return _populate_sqlite(connection, path)
    except sqlite3.Error as exc:
        raise InputError(f"{path.name}: SQLite error ({exc})") from exc
    finally:
        connection.close()


def _populate_sqlite(connection: sqlite3.Connection, path: Path) -> Dataset:
    """Run the queries; a driver-level failure is caught by the caller."""
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "positions" not in tables:
        raise InputError(
            f"{path.name}: no 'positions' table (expected a dump1090-recorder database)"
        )
    columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(positions)")]
    missing = [name for name in ("ts", "hex", "lat", "lon") if name not in columns]
    if missing:
        raise InputError(f"{path.name}: positions table is missing column(s): {', '.join(missing)}")
    wanted = ("ts", "hex", "lat", "lon", "alt_baro", "alt_geom", "flight")
    selected = [name for name in wanted if name in columns]
    quoted = ", ".join(f'"{name}"' for name in selected)
    observations: list[Observation] = []
    skipped = 0
    for row in connection.execute(f'SELECT {quoted} FROM "positions"'):
        record = dict(zip(selected, row, strict=True))
        t = _number(record.get("ts"))
        observation = _observation(t, record) if t is not None else None
        if observation is None:
            skipped += 1
        else:
            observations.append(observation)
    return Dataset(
        observations=observations,
        receiver=_receiver_from_db(connection, tables),
        skipped=skipped,
        source="sqlite",
        path=path,
    )


def load(path: str | Path, *, force_sqlite: bool = False) -> Dataset:
    """Load a recording, detecting the format automatically.

    Args:
        path: NDJSON export or SQLite database.
        force_sqlite: Interpret ``path`` as SQLite regardless of magic/extension.

    Raises:
        InputError: The file is missing, unreadable, malformed, or holds no
            position observations at all.
    """
    candidate = Path(path)
    if not candidate.exists():
        raise InputError(f"input not found: {candidate}")
    if not candidate.is_file():
        raise InputError(f"input is not a file: {candidate}")
    source = detect_format(candidate, force_sqlite=force_sqlite)
    dataset = _load_sqlite(candidate) if source == "sqlite" else _load_ndjson(candidate)
    if not dataset.observations:
        raise InputError(f"no position observations found in {candidate.name}")
    return dataset
