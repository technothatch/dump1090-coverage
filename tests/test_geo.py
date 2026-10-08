"""Geometry: haversine distances, bearings, sector assignment and the hex grid."""

from __future__ import annotations

import math

import pytest

from dump1090_coverage.geo import (
    SECTOR_COUNT,
    cell_at,
    cell_center,
    cell_corners,
    cell_key,
    cell_key_parse,
    haversine_km,
    initial_bearing_deg,
    project,
    sector_bounds,
    sector_index,
    sector_label,
    unproject,
)

RECEIVER = (51.47, -0.45)


def test_haversine_identical_points_is_zero() -> None:
    assert haversine_km(51.47, -0.45, 51.47, -0.45) == 0.0


def test_haversine_one_degree_of_latitude() -> None:
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.05)


def test_haversine_london_to_paris() -> None:
    distance = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340.0 < distance < 348.0


def test_haversine_is_symmetric() -> None:
    forward = haversine_km(51.47, -0.45, 53.48, -2.24)
    backward = haversine_km(53.48, -2.24, 51.47, -0.45)
    assert forward == pytest.approx(backward)


def test_haversine_across_the_antimeridian() -> None:
    assert haversine_km(0.0, 179.0, 0.0, -179.0) == pytest.approx(222.4, abs=1.0)


def test_bearing_due_north() -> None:
    assert initial_bearing_deg(51.47, -0.45, 51.57, -0.45) == pytest.approx(0.0, abs=0.01)


def test_bearing_due_south() -> None:
    assert initial_bearing_deg(51.47, -0.45, 51.37, -0.45) == pytest.approx(180.0, abs=0.01)


def test_bearing_due_east() -> None:
    bearing = initial_bearing_deg(51.47, -0.45, 51.47, -0.40)
    assert bearing == pytest.approx(90.0, abs=0.1)


def test_bearing_due_west() -> None:
    bearing = initial_bearing_deg(51.47, -0.45, 51.47, -0.50)
    assert bearing == pytest.approx(270.0, abs=0.1)


def test_bearing_north_east_is_45_degrees() -> None:
    bearing = initial_bearing_deg(*RECEIVER, 51.8499, 0.1677)
    assert bearing == pytest.approx(45.0, abs=0.5)


def test_bearing_is_always_in_range_and_wraps() -> None:
    bearing = initial_bearing_deg(51.47, -0.45, 51.50, -0.46)
    assert 340.0 < bearing < 360.0
    assert 0.0 <= bearing < 360.0


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [(0.0, 0), (9.999, 0), (10.0, 1), (45.0, 4), (359.99, 35), (360.0, 0)],
)
def test_sector_index_boundaries(bearing: float, expected: int) -> None:
    assert sector_index(bearing) == expected


def test_sector_index_stays_in_range_for_odd_input() -> None:
    assert sector_index(-0.5) == 35
    assert 0 <= sector_index(721.0) < SECTOR_COUNT


def test_sector_bounds_cover_the_compass() -> None:
    assert sector_bounds(0) == (0.0, 10.0)
    assert sector_bounds(35) == (350.0, 360.0)


def test_sector_bounds_rejects_out_of_range_index() -> None:
    with pytest.raises(ValueError, match="sector index"):
        sector_bounds(36)
    with pytest.raises(ValueError, match="sector index"):
        sector_bounds(-1)


def test_sector_label_formats() -> None:
    assert sector_label(0) == "000-010"
    assert sector_label(9) == "090-100"
    assert sector_label(35) == "350-360"


def test_project_is_zero_at_the_receiver() -> None:
    east, north = project(*RECEIVER, *RECEIVER)
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north == pytest.approx(0.0, abs=1e-9)


def test_project_east_north_signs() -> None:
    east, north = project(*RECEIVER, 51.47, -0.35)
    assert 6.0 < east < 8.0
    assert north == pytest.approx(0.0, abs=1e-9)
    east, north = project(*RECEIVER, 52.47, -0.45)
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north > 110.0


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(51.5, -0.4), (50.0, 1.5), (53.0, -3.0), (49.9, 0.4), (54.1, 0.5)],
)
def test_project_unproject_round_trip(lat: float, lon: float) -> None:
    east, north = project(*RECEIVER, lat, lon)
    new_lat, new_lon = unproject(*RECEIVER, east, north)
    assert new_lat == pytest.approx(lat, abs=1e-9)
    assert new_lon == pytest.approx(lon, abs=1e-9)


def test_cell_at_receiver_is_the_origin_cell() -> None:
    assert cell_at(0.0, 0.0, 2.5) == (0, 0)


def test_cell_center_of_origin_is_zero() -> None:
    assert cell_center(0, 0, 2.5) == (0.0, 0.0)


def test_every_point_lies_within_its_own_cell() -> None:
    size = 2.5
    for east in [x * 1.7 for x in range(-15, 16)]:
        for north in [y * 1.7 for y in range(-15, 16)]:
            q, r = cell_at(east, north, size)
            center_east, center_north = cell_center(q, r, size)
            distance = math.hypot(east - center_east, north - center_north)
            assert distance <= size + 1e-9, f"({east}, {north}) -> {q},{r}"


def test_neighbouring_cells_are_spaced_by_root_three_size() -> None:
    size = 4.0
    a = cell_center(0, 0, size)
    b = cell_center(1, 0, size)
    c = cell_center(0, 1, size)
    assert math.dist(a, b) == pytest.approx(math.sqrt(3) * size)
    assert math.dist(a, c) == pytest.approx(math.sqrt(3) * size)


def test_cell_at_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="cell size"):
        cell_at(1.0, 1.0, 0.0)


def test_cell_corners_form_a_regular_hexagon() -> None:
    size = 3.0
    corners = cell_corners(10.0, -5.0, size)
    assert len(corners) == 6
    for east, north in corners:
        assert math.dist((east, north), (10.0, -5.0)) == pytest.approx(size)
    for index in range(6):
        first = corners[index]
        second = corners[(index + 1) % 6]
        assert math.dist(first, second) == pytest.approx(size)


def test_cell_key_round_trip() -> None:
    for q, r in [(0, 0), (-3, 7), (12, -4)]:
        assert cell_key_parse(cell_key(q, r)) == (q, r)
    assert cell_key(-3, 7) == "-3,7"
