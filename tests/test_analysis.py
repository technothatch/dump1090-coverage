"""Aggregation: percentiles, histogram, grid, sectors, daily statistics."""

from __future__ import annotations

import pytest

from dump1090_coverage.analysis import (
    ALT_BUCKETS,
    Report,
    altitude_histogram,
    build_report,
    percentile,
)
from dump1090_coverage.errors import CoverageError
from dump1090_coverage.models import Observation
from helpers import RECEIVER_LAT, RECEIVER_LON

RECEIVER = (51.47, -0.45)


def make(t: float, hex_id: str, lat: float, lon: float, alt: float | None = None) -> Observation:
    return Observation(t=t, hex=hex_id, lat=lat, lon=lon, alt_ft=alt)


def test_percentile_median_interpolates() -> None:
    values = [float(value) for value in range(1, 11)]
    assert percentile(values, 50) == pytest.approx(5.5)


def test_percentile_edges_are_min_and_max() -> None:
    values = [3.0, 1.0, 2.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 3.0


def test_percentile_quarter() -> None:
    values = [float(value) for value in range(1, 11)]
    assert percentile(values, 25) == pytest.approx(3.25)


def test_percentile_single_value() -> None:
    assert percentile([42.0], 90) == 42.0


def test_percentile_ignores_input_order() -> None:
    ascending = [float(value) for value in range(1, 11)]
    assert percentile(list(reversed(ascending)), 75) == pytest.approx(7.75)


def test_percentile_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


@pytest.mark.parametrize("p", [-1.0, 101.0, -0.001])
def test_percentile_rejects_out_of_range_percentile(p: float) -> None:
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        percentile([1.0, 2.0], p)


def test_altitude_histogram_buckets_from_the_sample(sample_report: Report) -> None:
    histogram = dict(sample_report.altitude)
    assert sum(histogram.values()) == sample_report.positions == 21
    assert histogram["0-999"] == 4  # four "ground" positions
    assert histogram["40000+"] == 1
    assert histogram["unknown"] == 1
    assert histogram["30000-34999"] == 4


def test_altitude_histogram_labels_and_unknown_count() -> None:
    observations = [
        make(1.0, "aa", 51.4, -0.4, None),
        make(2.0, "bb", 51.4, -0.4, -50.0),
        make(3.0, "cc", 51.4, -0.4, 40000.0),
        make(4.0, "dd", 51.4, -0.4, 999.0),
    ]
    histogram = dict(altitude_histogram(observations))
    assert histogram["0-999"] == 2  # 999 ft and the negative altitude
    assert histogram[f"{ALT_BUCKETS[-1]}+"] == 1
    assert histogram["unknown"] == 1
    assert list(histogram)[-1] == "unknown"


def test_build_report_rejects_empty_input() -> None:
    with pytest.raises(CoverageError, match="no position observations"):
        build_report([], receiver_lat=51.0, receiver_lon=0.0, cell_km=5.0)


@pytest.mark.parametrize("cell_km", [0.0, -5.0, float("nan")])
def test_build_report_rejects_bad_cell_size(cell_km: float) -> None:
    observations = [make(1.0, "aa", 51.4, -0.4)]
    with pytest.raises(CoverageError, match="--cell-km"):
        build_report(observations, receiver_lat=51.0, receiver_lon=0.0, cell_km=cell_km)


@pytest.mark.parametrize(("lat", "lon"), [(95.0, 0.0), (-91.0, 0.0), (51.0, 181.0), (51.0, -200.0)])
def test_build_report_rejects_invalid_receiver(lat: float, lon: float) -> None:
    observations = [make(1.0, "aa", 51.4, -0.4)]
    with pytest.raises(CoverageError, match="receiver"):
        build_report(observations, receiver_lat=lat, receiver_lon=lon, cell_km=5.0)


def test_sample_report_headline_numbers(sample_report: Report) -> None:
    assert sample_report.positions == 21
    assert sample_report.aircraft == 6
    assert sample_report.skipped == 1
    assert sample_report.receiver_lat == RECEIVER_LAT
    assert sample_report.receiver_lon == RECEIVER_LON
    assert sample_report.cell_km == 5.0
    assert sample_report.size_km == 2.5
    assert sample_report.hours == pytest.approx(48.0)
    assert sample_report.messages_per_hour == pytest.approx(21 / 48)


def test_sample_report_range_percentiles(sample_report: Report) -> None:
    assert 295.0 < sample_report.max_range_km < 305.0
    assert 0.0 < sample_report.p50_range_km < sample_report.p90_range_km
    assert sample_report.p90_range_km <= sample_report.max_range_km
    assert sample_report.p95_range_km <= sample_report.max_range_km


def test_sample_report_days_and_best_worst(sample_report: Report) -> None:
    assert [day.day for day in sample_report.days] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
    ]
    assert [day.positions for day in sample_report.days] == [12, 7, 2]
    assert sample_report.best_day is not None
    assert sample_report.best_day.day == "2026-10-01"
    assert sample_report.best_day.aircraft == 6
    assert sample_report.worst_day is not None
    assert sample_report.worst_day.day == "2026-10-03"
    assert sample_report.worst_day.aircraft == 2


def test_sample_report_cells_partition_every_position(sample_report: Report) -> None:
    assert sample_report.cells
    assert sum(cell.positions for cell in sample_report.cells) == 21
    for cell in sample_report.cells:
        assert 1 <= cell.aircraft <= 6
        assert cell.positions >= 1
        assert cell.max_range_km >= 0.0


def test_sample_report_sectors_sum_to_positions(sample_report: Report) -> None:
    assert len(sample_report.sectors) == 36
    assert sum(sector.count for sector in sample_report.sectors) == 21
    north = sample_report.sectors[0]
    assert north.count == 5
    east = sample_report.sectors[9]
    assert east.count == 2
    assert east.max_km == pytest.approx(120.0, abs=0.5)
    empty = [sector for sector in sample_report.sectors if sector.count == 0]
    assert empty
    for sector in empty:
        assert sector.max_km is None and sector.p50_km is None and sector.p90_km is None


def test_empty_sector_statistics_are_none() -> None:
    observations = [make(1.0, "aa", 52.47, -0.45)]  # due north only
    report = build_report(observations, receiver_lat=51.0, receiver_lon=-0.45, cell_km=5.0)
    assert report.sectors[0].count == 1
    assert report.sectors[0].max_km is not None
    assert report.sectors[18].count == 0
    assert report.sectors[18].p90_km is None


def test_cell_counts_unique_aircraft_per_cell() -> None:
    observations = [
        make(1.0, "aaaaaa", 51.5, -0.45),
        make(2.0, "bbbbbb", 51.501, -0.449),
        make(3.0, "aaaaaa", 51.502, -0.448),
    ]
    report = build_report(observations, receiver_lat=51.5, receiver_lon=-0.45, cell_km=100.0)
    assert len(report.cells) == 1
    cell = report.cells[0]
    assert cell.aircraft == 2
    assert cell.positions == 3
    assert cell.q == 0 and cell.r == 0


def test_single_observation_report_is_stable() -> None:
    observations = [make(1790812800.0, "aaaaaa", 51.6, -0.4)]
    report = build_report(observations, receiver_lat=51.47, receiver_lon=-0.45, cell_km=5.0)
    assert report.positions == 1
    assert report.aircraft == 1
    assert report.hours == 0.0
    assert report.messages_per_hour == 0.0
    assert report.p50_range_km == report.max_range_km
    assert report.best_day is not None and report.worst_day is not None
    assert report.best_day.day == report.worst_day.day == "2026-10-01"
