"""The GeoJSON renderer: one closed hexagon Polygon per grid cell."""

from __future__ import annotations

import json
from pathlib import Path

from dump1090_coverage.analysis import Report, build_report
from dump1090_coverage.read import load
from dump1090_coverage.render import render_geojson
from helpers import RECEIVER_LAT, RECEIVER_LON


def geojson(sample_report: Report) -> dict[str, object]:
    """Render and parse the GeoJSON of a report."""
    document: dict[str, object] = json.loads(render_geojson(sample_report))
    return document


def test_geojson_is_a_feature_collection(sample_report: Report) -> None:
    document = geojson(sample_report)
    assert document["type"] == "FeatureCollection"
    assert isinstance(document["features"], list)


def test_geojson_feature_count_matches_cells(sample_report: Report) -> None:
    features = geojson(sample_report)["features"]
    assert len(features) == len(sample_report.cells)
    assert len(features) > 0


def test_geojson_feature_properties(sample_report: Report) -> None:
    feature = geojson(sample_report)["features"][0]
    properties = feature["properties"]  # type: ignore[index]
    expected = sample_report.cells[0]
    wanted = ("cell", "q", "r", "aircraft", "positions", "center_lat", "center_lon", "max_range_km")
    for key in wanted:
        assert key in properties
    assert properties["cell"] == expected.key
    assert properties["q"] == expected.q
    assert properties["r"] == expected.r
    assert properties["aircraft"] == expected.aircraft
    assert properties["positions"] == expected.positions
    assert properties["center_lat"] == round(expected.lat, 6)


def test_geojson_ring_is_closed_with_seven_points(sample_report: Report) -> None:
    for feature in geojson(sample_report)["features"]:  # type: ignore[union-attr]
        geometry = feature["geometry"]
        assert geometry["type"] == "Polygon"
        rings = geometry["coordinates"]
        assert len(rings) == 1
        ring = rings[0]
        assert len(ring) == 7
        assert ring[0] == ring[-1]
        for lon, lat in ring:
            assert -180.0 <= lon <= 180.0
            assert -90.0 <= lat <= 90.0


def test_geojson_top_level_properties(sample_report: Report) -> None:
    properties = geojson(sample_report)["properties"]  # type: ignore[index]
    assert properties["receiver_lat"] == 51.47
    assert properties["receiver_lon"] == -0.45
    assert properties["cell_km"] == 5.0
    assert properties["positions"] == 21
    assert properties["aircraft"] == 6


def test_geojson_cell_centres_are_near_their_hexes(sample_report: Report) -> None:
    for feature in geojson(sample_report)["features"]:  # type: ignore[union-attr]
        properties = feature["properties"]
        ring = feature["geometry"]["coordinates"][0]
        lons = [point[0] for point in ring[:-1]]
        lats = [point[1] for point in ring[:-1]]
        assert min(lons) <= properties["center_lon"] <= max(lons)
        assert min(lats) <= properties["center_lat"] <= max(lats)


def test_geojson_output_is_deterministic(sample_report: Report) -> None:
    assert render_geojson(sample_report) == render_geojson(sample_report)


def test_coarser_cells_produce_fewer_features(sample_report: Report, sample_path: Path) -> None:
    dataset = load(sample_path)
    coarse = build_report(
        dataset.observations,
        receiver_lat=RECEIVER_LAT,
        receiver_lon=RECEIVER_LON,
        cell_km=50.0,
    )
    assert len(coarse.cells) < len(sample_report.cells)
    assert len(geojson(coarse)["features"]) == len(coarse.cells)  # type: ignore[union-attr]
