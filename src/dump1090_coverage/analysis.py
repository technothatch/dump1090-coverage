"""Aggregation: turn a list of observations into a coverage report.

Everything here is a pure function of the input rows — no I/O, no clock — so
the numbers in the HTML, GeoJSON and text outputs are trivially testable.

What gets computed:

* a **hex grid** over the receiver's range, counting unique aircraft and
  positions per cell (the heatmap);
* **36 bearing sectors** of 10 degrees with max / p50 / p90 range;
* overall range percentiles, messages per hour, unique ICAOs per day,
  an altitude histogram and the best/worst day.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dump1090_coverage.errors import CoverageError
from dump1090_coverage.geo import (
    SECTOR_COUNT,
    SECTOR_DEG,
    cell_at,
    cell_center,
    cell_key,
    haversine_km,
    initial_bearing_deg,
    project,
    sector_index,
    unproject,
)
from dump1090_coverage.models import Observation

__all__ = [
    "ALT_BUCKETS",
    "Cell",
    "Day",
    "Report",
    "Sector",
    "altitude_histogram",
    "build_report",
    "percentile",
]

#: Altitude histogram upper bounds in feet; everything at or above the last one
#: lands in its own open-ended bucket.
ALT_BUCKETS: tuple[int, ...] = (1000, 3000, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000)


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile (the ``numpy.percentile`` default).

    ``p`` must be in ``[0, 100]`` and ``values`` must not be empty:
    ``percentile([1.0, ..., 10.0], 50) == 5.5``, ``p=0`` is the minimum and
    ``p=100`` the maximum.
    """
    if not values:
        raise ValueError("percentile() of empty sequence")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"percentile must be in [0, 100], got {p}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    return float(ordered[low]) + (float(ordered[high]) - float(ordered[low])) * (rank - low)


def _bucket_index(alt_ft: float) -> int:
    """Index of the histogram bucket an altitude belongs to."""
    if alt_ft < 0:
        alt_ft = 0.0
    for index, upper in enumerate(ALT_BUCKETS):
        if alt_ft < upper:
            return index
    return len(ALT_BUCKETS)


def altitude_histogram(observations: Sequence[Observation]) -> list[tuple[str, int]]:
    """Fixed altitude buckets plus an ``unknown`` bucket; labels are in feet."""
    counts = [0] * (len(ALT_BUCKETS) + 2)
    for observation in observations:
        if observation.alt_ft is None:
            counts[-1] += 1
        else:
            counts[_bucket_index(observation.alt_ft)] += 1
    lower_edges = (0, *ALT_BUCKETS[:-1])
    labels = [f"{lower}-{upper - 1}" for lower, upper in zip(lower_edges, ALT_BUCKETS, strict=True)]
    labels.append(f"{ALT_BUCKETS[-1]}+")
    labels.append("unknown")
    return list(zip(labels, counts, strict=True))


@dataclass(frozen=True, slots=True)
class Cell:
    """One hex cell of the coverage grid."""

    q: int
    r: int
    lat: float
    lon: float
    aircraft: int
    positions: int
    max_range_km: float

    @property
    def key(self) -> str:
        """Stable identifier of the cell, ``"q,r"``."""
        return cell_key(self.q, self.r)


@dataclass(frozen=True, slots=True)
class Sector:
    """Range statistics for one 10-degree bearing sector."""

    index: int
    count: int
    aircraft: int
    max_km: float | None
    p50_km: float | None
    p90_km: float | None

    @property
    def start_deg(self) -> float:
        """Inclusive lower bearing of the sector."""
        return self.index * SECTOR_DEG


@dataclass(frozen=True, slots=True)
class Day:
    """One UTC calendar day of traffic."""

    day: str
    positions: int
    aircraft: int


@dataclass(frozen=True, slots=True)
class Report:
    """Every statistic the renderers need."""

    receiver_lat: float
    receiver_lon: float
    cell_km: float
    start: float
    end: float
    positions: int
    aircraft: int
    skipped: int
    messages_per_hour: float
    max_range_km: float
    p50_range_km: float
    p90_range_km: float
    p95_range_km: float
    cells: list[Cell]
    sectors: list[Sector]
    days: list[Day]
    altitude: list[tuple[str, int]]
    best_day: Day | None
    worst_day: Day | None

    @property
    def size_km(self) -> float:
        """Hex circumradius: half of the configured cell width."""
        return self.cell_km / 2.0

    @property
    def hours(self) -> float:
        """Length of the recorded period in hours (0.0 for a single instant)."""
        return max(0.0, self.end - self.start) / 3600.0


@dataclass
class _CellAccumulator:
    """Mutable per-cell state while streaming through the observations."""

    hexes: set[str] = field(default_factory=set)
    positions: int = 0
    max_range_km: float = 0.0


@dataclass
class _DayAccumulator:
    """Mutable per-day state while streaming through the observations."""

    hexes: set[str] = field(default_factory=set)
    positions: int = 0


def build_report(
    observations: Sequence[Observation],
    *,
    receiver_lat: float,
    receiver_lon: float,
    cell_km: float,
    skipped: int = 0,
) -> Report:
    """Aggregate observations into a :class:`Report`.

    Args:
        observations: Position rows, in any order.
        receiver_lat: Receiver latitude in decimal degrees.
        receiver_lon: Receiver longitude in decimal degrees.
        cell_km: Point-to-point width of a hex cell, in kilometres.
        skipped: Rows the reader discarded (no position), reported for context.

    Raises:
        CoverageError: No observations, an invalid cell size, or an invalid
            receiver position.
    """
    if not observations:
        raise CoverageError("no position observations to analyse")
    if not math.isfinite(cell_km) or cell_km <= 0:
        raise CoverageError(f"--cell-km must be a positive number, got {cell_km!r}")
    if not math.isfinite(receiver_lat) or not -90.0 <= receiver_lat <= 90.0:
        raise CoverageError(f"receiver latitude must be between -90 and 90, got {receiver_lat!r}")
    if not math.isfinite(receiver_lon) or not -180.0 <= receiver_lon <= 180.0:
        raise CoverageError(
            f"receiver longitude must be between -180 and 180, got {receiver_lon!r}"
        )

    start = min(observation.t for observation in observations)
    end = max(observation.t for observation in observations)
    size = cell_km / 2.0
    ranges: list[float] = []
    sector_ranges: list[list[float]] = [[] for _ in range(SECTOR_COUNT)]
    sector_hexes: list[set[str]] = [set() for _ in range(SECTOR_COUNT)]
    grid: dict[tuple[int, int], _CellAccumulator] = {}
    days: dict[str, _DayAccumulator] = {}
    all_hexes: set[str] = set()

    for observation in observations:
        distance = haversine_km(receiver_lat, receiver_lon, observation.lat, observation.lon)
        ranges.append(distance)
        sector = sector_index(
            initial_bearing_deg(receiver_lat, receiver_lon, observation.lat, observation.lon)
        )
        sector_ranges[sector].append(distance)
        sector_hexes[sector].add(observation.hex)

        east, north = project(receiver_lat, receiver_lon, observation.lat, observation.lon)
        cell = grid.setdefault(cell_at(east, north, size), _CellAccumulator())
        cell.hexes.add(observation.hex)
        cell.positions += 1
        cell.max_range_km = max(cell.max_range_km, distance)

        day = datetime.fromtimestamp(observation.t, tz=UTC).date().isoformat()
        bucket = days.setdefault(day, _DayAccumulator())
        bucket.hexes.add(observation.hex)
        bucket.positions += 1
        all_hexes.add(observation.hex)

    hours = (end - start) / 3600.0
    cells = _build_cells(grid, receiver_lat, receiver_lon, size)
    day_list = [
        Day(day=name, positions=bucket.positions, aircraft=len(bucket.hexes))
        for name, bucket in sorted(days.items())
    ]

    return Report(
        receiver_lat=receiver_lat,
        receiver_lon=receiver_lon,
        cell_km=cell_km,
        start=start,
        end=end,
        positions=len(observations),
        aircraft=len(all_hexes),
        skipped=skipped,
        messages_per_hour=len(observations) / hours if hours > 0 else 0.0,
        max_range_km=max(ranges),
        p50_range_km=percentile(ranges, 50),
        p90_range_km=percentile(ranges, 90),
        p95_range_km=percentile(ranges, 95),
        cells=cells,
        sectors=_build_sectors(sector_ranges, sector_hexes),
        days=day_list,
        altitude=altitude_histogram(observations),
        best_day=max(day_list, key=lambda day: (day.aircraft, day.positions)) if day_list else None,
        worst_day=min(day_list, key=lambda day: (day.aircraft, day.positions))
        if day_list
        else None,
    )


def _build_cells(
    grid: dict[tuple[int, int], _CellAccumulator],
    receiver_lat: float,
    receiver_lon: float,
    size: float,
) -> list[Cell]:
    """Turn the streaming accumulators into cells sorted by traffic density."""
    cells = []
    for (q, r), cell in grid.items():
        east, north = cell_center(q, r, size)
        lat, lon = unproject(receiver_lat, receiver_lon, east, north)
        cells.append(
            Cell(
                q=q,
                r=r,
                lat=lat,
                lon=lon,
                aircraft=len(cell.hexes),
                positions=cell.positions,
                max_range_km=cell.max_range_km,
            )
        )
    cells.sort(key=lambda cell: (-cell.aircraft, -cell.positions, cell.q, cell.r))
    return cells


def _build_sectors(sector_ranges: list[list[float]], sector_hexes: list[set[str]]) -> list[Sector]:
    """All 36 sectors are always present; empty ones carry ``None`` ranges."""
    sectors = []
    for index in range(SECTOR_COUNT):
        values = sector_ranges[index]
        sectors.append(
            Sector(
                index=index,
                count=len(values),
                aircraft=len(sector_hexes[index]),
                max_km=max(values) if values else None,
                p50_km=percentile(values, 50) if values else None,
                p90_km=percentile(values, 90) if values else None,
            )
        )
    return sectors
