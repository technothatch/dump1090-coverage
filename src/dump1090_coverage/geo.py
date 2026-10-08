"""Geometry: great-circle maths, bearing sectors and the local hex grid.

Pure maths on WGS-84 degrees and local kilometres — no I/O, no clock, no state.
Positions are projected onto an east/north plane centred on the receiver (a
local equirectangular projection, accurate to well under 1% across the few
hundred kilometres an ADS-B receiver can see), and bucketed into a pointy-top
hexagonal lattice whose cells are ``cell_km`` across their points.
"""

from __future__ import annotations

import math

__all__ = [
    "EARTH_RADIUS_KM",
    "SECTOR_COUNT",
    "SECTOR_DEG",
    "cell_at",
    "cell_center",
    "cell_corners",
    "cell_key",
    "cell_key_parse",
    "haversine_km",
    "initial_bearing_deg",
    "project",
    "sector_bounds",
    "sector_index",
    "sector_label",
    "unproject",
]

#: Mean Earth radius in kilometres (IUGG mean radius, R1).
EARTH_RADIUS_KM = 6371.0088

#: Bearings are bucketed into this many equal sectors (36 x 10 degrees).
SECTOR_COUNT = 36
SECTOR_DEG = 360.0 / SECTOR_COUNT


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing from point 1 to point 2, in ``[0, 360)``.

    0 degrees is true north, 90 degrees east.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def sector_index(bearing_deg: float) -> int:
    """Map any bearing onto its ``0``-``35`` sector (sector 0 starts at north)."""
    return int(bearing_deg // SECTOR_DEG) % SECTOR_COUNT


def sector_bounds(index: int) -> tuple[float, float]:
    """Inclusive start and exclusive end bearing of a sector, in degrees."""
    if not 0 <= index < SECTOR_COUNT:
        raise ValueError(f"sector index must be 0-{SECTOR_COUNT - 1}, got {index}")
    start = index * SECTOR_DEG
    return start, start + SECTOR_DEG


def sector_label(index: int) -> str:
    """Human label for a sector, e.g. ``"090-100"``."""
    start, end = sector_bounds(index)
    return f"{start:03.0f}-{end:03.0f}"


def project(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """Local east/north kilometres of ``(lat, lon)`` relative to ``(lat0, lon0)``."""
    d_lat = math.radians(lat - lat0)
    d_lon = math.radians((lon - lon0 + 180.0) % 360.0 - 180.0)
    mean_lat = math.radians((lat + lat0) / 2.0)
    east = EARTH_RADIUS_KM * d_lon * max(math.cos(mean_lat), 1e-12)
    north = EARTH_RADIUS_KM * d_lat
    return east, north


def unproject(lat0: float, lon0: float, east_km: float, north_km: float) -> tuple[float, float]:
    """Inverse of :func:`project` — local kilometres back to decimal degrees."""
    lat = lat0 + math.degrees(north_km / EARTH_RADIUS_KM)
    mean_lat = math.radians((lat + lat0) / 2.0)
    d_lon = east_km / (EARTH_RADIUS_KM * max(math.cos(mean_lat), 1e-12))
    return lat, lon0 + math.degrees(d_lon)


def _cube_round(x: float, y: float, z: float) -> tuple[int, int, int]:
    """Round a cube-coordinate triple back onto the integer lattice."""
    rx, ry, rz = round(x), round(y), round(z)
    x_diff, y_diff, z_diff = abs(rx - x), abs(ry - y), abs(rz - z)
    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(ry), int(rz)


def cell_at(east_km: float, north_km: float, size_km: float) -> tuple[int, int]:
    """Hex cell (axial ``q, r``) containing a point of the local plane.

    ``size_km`` is the circumradius of a cell (``cell_km / 2``); the pointy-top
    axial formulas below are the standard ones from the hex-grid literature.
    """
    if size_km <= 0:
        raise ValueError(f"cell size must be positive, got {size_km}")
    q = (math.sqrt(3) / 3 * east_km - 1 / 3 * north_km) / size_km
    r = (2 / 3 * north_km) / size_km
    return _round_hex(q, r)


def _round_hex(q: float, r: float) -> tuple[int, int]:
    x, z = q, r
    y = -x - z
    _rx, ry, rz = _cube_round(x, y, z)
    return int(-ry - rz), int(rz)


def cell_center(q: int, r: int, size_km: float) -> tuple[float, float]:
    """East/north kilometres of the centre of cell ``(q, r)``."""
    east = size_km * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
    north = size_km * 1.5 * r
    return east, north


def cell_corners(east_km: float, north_km: float, size_km: float) -> list[tuple[float, float]]:
    """The six vertices of a cell, in east/north kilometres, north first."""
    corners: list[tuple[float, float]] = []
    for i in range(6):
        angle = math.radians(90.0 + 60.0 * i)
        corners.append((east_km + size_km * math.cos(angle), north_km + size_km * math.sin(angle)))
    return corners


def cell_key(q: int, r: int) -> str:
    """Stable string identifier for a cell, e.g. ``"-3,7"``."""
    return f"{q},{r}"


def cell_key_parse(key: str) -> tuple[int, int]:
    """Inverse of :func:`cell_key`."""
    q_text, _, r_text = key.partition(",")
    return int(q_text), int(r_text)
