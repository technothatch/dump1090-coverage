"""The one record every other module works with.

A recording is a stream of *position observations*: one aircraft, at one
instant, with a latitude/longitude. Both supported inputs (the NDJSON export of
``dump1090-recorder`` and its SQLite database) are normalised into this shape
before anything is analysed, so the analysis code never has to care where the
data came from.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Observation"]


@dataclass(frozen=True, slots=True)
class Observation:
    """A single aircraft seen at a single point in time.

    Attributes:
        t: Unix epoch seconds of the snapshot (or database row).
        hex: Lower-case ICAO 24-bit address, e.g. ``"40621d"``.
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        alt_ft: Altitude in feet; ``0.0`` for ``"ground"``, ``None`` if unknown.
        flight: Trimmed callsign when the recording carried one.
    """

    t: float
    hex: str
    lat: float
    lon: float
    alt_ft: float | None = None
    flight: str | None = None
