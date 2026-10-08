"""Renderers: self-contained HTML, GeoJSON and a plain-text summary.

The HTML output is deliberately dependency-free — inline CSS, an inline SVG
heatmap drawn straight from the report, and the whole report embedded as JSON
in a ``<script type="application/json">`` tag. No CDN, no fonts, no network:
the file opens from a ``file://`` URL with no connectivity at all.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from dump1090_coverage.analysis import Cell, Report, Sector
from dump1090_coverage.geo import SECTOR_DEG, cell_center, cell_corners, sector_label, unproject

__all__ = ["render", "render_geojson", "render_html", "render_text"]

#: Heat-map colour ramp: normalised aircraft count -> RGB.
_COLOR_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (18, 44, 74)),
    (0.5, (47, 158, 143)),
    (0.75, (233, 196, 106)),
    (1.0, (231, 111, 81)),
)

#: SVG canvas size in pixels.
_SVG_SIZE = 800.0

#: Ring step candidates (km) used to pick a readable range-ring spacing.
_RING_STEPS: tuple[float, ...] = (10.0, 20.0, 25.0, 50.0, 100.0, 200.0, 250.0, 500.0, 1000.0)


def render(report: Report, fmt: str) -> str:
    """Render a report as ``"html"``, ``"geojson"`` or ``"text"``."""
    if fmt == "html":
        return render_html(report)
    if fmt == "geojson":
        return render_geojson(report)
    if fmt == "text":
        return render_text(report)
    raise ValueError(f"unknown format {fmt!r} (expected html, geojson or text)")


def _iso(epoch: float) -> str:
    """UTC ``YYYY-MM-DDTHH:MM:SSZ`` timestamp of an epoch second."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: float | None, digits: int = 1) -> str:
    """Fixed-precision number, or ``-`` when the statistic does not exist."""
    return "-" if value is None else f"{value:.{digits}f}"


def render_text(report: Report) -> str:
    """Human-readable summary: headline stats, sector table, histogram, days."""
    lines: list[str] = []
    add = lines.append
    add("dump1090-coverage summary")
    add("=" * 25)
    add(f"receiver       {report.receiver_lat:.4f}, {report.receiver_lon:.4f}")
    add(f"cell size      {report.cell_km:.1f} km ({report.size_km:.1f} km hex radius)")
    add(f"period         {_iso(report.start)} .. {_iso(report.end)}  ({report.hours:.1f} h)")
    add(f"positions      {report.positions} in {len(report.cells)} cells")
    add(f"unique ICAOs   {report.aircraft}")
    add(f"skipped rows   {report.skipped}")
    add(f"messages/hour  {report.messages_per_hour:.1f}")
    add(
        "range (km)     max "
        f"{_num(report.max_range_km)} | p50 {_num(report.p50_range_km)} | "
        f"p90 {_num(report.p90_range_km)} | p95 {_num(report.p95_range_km)}"
    )
    if report.best_day is not None:
        add(
            f"best day       {report.best_day.day} "
            f"({report.best_day.aircraft} ICAOs, {report.best_day.positions} positions)"
        )
    if report.worst_day is not None:
        add(
            f"worst day      {report.worst_day.day} "
            f"({report.worst_day.aircraft} ICAOs, {report.worst_day.positions} positions)"
        )

    add("")
    add(f"Range by bearing ({SECTOR_DEG:.0f}-degree sectors)")
    add(f"  {'sector':<8}{'count':>8}{'aircraft':>10}{'p50 km':>10}{'p90 km':>10}{'max km':>10}")
    for sector in report.sectors:
        add(
            f"  {sector_label(sector.index):<8}{sector.count:>8}{sector.aircraft:>10}"
            f"{_num(sector.p50_km):>10}{_num(sector.p90_km):>10}{_num(sector.max_km):>10}"
        )

    add("")
    add("Altitude histogram (ft)")
    add(f"  {'bucket':<16}{'count':>8}")
    for bucket, count in report.altitude:
        add(f"  {bucket:<16}{count:>8}")

    add("")
    add("Daily activity (UTC)")
    add(f"  {'day':<12}{'positions':>12}{'ICAOs':>10}")
    for day in report.days:
        add(f"  {day.day:<12}{day.positions:>12}{day.aircraft:>10}")
    if not report.days:
        add("  (no days)")
    return "\n".join(lines) + "\n"


def _cell_polygon(cell: Cell, size_km: float, receiver: tuple[float, float]) -> list[list[float]]:
    """Closed GeoJSON ring (lon/lat) for one hex cell."""
    east, north = cell_center(cell.q, cell.r, size_km)
    ring: list[list[float]] = []
    for corner_east, corner_north in cell_corners(east, north, size_km):
        lat, lon = unproject(receiver[0], receiver[1], corner_east, corner_north)
        ring.append([round(lon, 6), round(lat, 6)])
    ring.append(list(ring[0]))
    return ring


def render_geojson(report: Report) -> str:
    """A FeatureCollection with one Polygon per hex cell plus headline metadata."""
    receiver = (report.receiver_lat, report.receiver_lon)
    features = [
        {
            "type": "Feature",
            "properties": {
                "cell": cell.key,
                "q": cell.q,
                "r": cell.r,
                "aircraft": cell.aircraft,
                "positions": cell.positions,
                "center_lat": round(cell.lat, 6),
                "center_lon": round(cell.lon, 6),
                "max_range_km": round(cell.max_range_km, 3),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [_cell_polygon(cell, report.size_km, receiver)],
            },
        }
        for cell in report.cells
    ]
    collection = {
        "type": "FeatureCollection",
        "properties": {
            "receiver_lat": report.receiver_lat,
            "receiver_lon": report.receiver_lon,
            "cell_km": report.cell_km,
            "positions": report.positions,
            "aircraft": report.aircraft,
            "max_range_km": round(report.max_range_km, 3),
        },
        "features": features,
    }
    return json.dumps(collection, indent=2) + "\n"


def _color(value: float) -> str:
    """Map a normalised ``0..1`` value onto the heat ramp as ``#rrggbb``."""
    t = min(1.0, max(0.0, value))
    lower, lower_rgb = _COLOR_STOPS[0]
    for upper, upper_rgb in _COLOR_STOPS[1:]:
        if t <= upper:
            span = upper - lower
            mix = 0.0 if span == 0 else (t - lower) / span
            channels = [
                round(lo + (hi - lo) * mix) for lo, hi in zip(lower_rgb, upper_rgb, strict=True)
            ]
            return "#{:02x}{:02x}{:02x}".format(*channels)
        lower, lower_rgb = upper, upper_rgb
    red, green, blue = lower_rgb
    return f"#{red:02x}{green:02x}{blue:02x}"


def _ring_step(limit: float) -> float:
    """A range-ring spacing that yields three to five rings for ``limit`` km."""
    for step in _RING_STEPS:
        if limit / step <= 4.5:
            return step
    return _RING_STEPS[-1]


def _heatmap_svg(report: Report) -> str:
    """Inline SVG: hex heat map, range rings, receiver marker and legend."""
    size = report.size_km
    pad = size + 15.0
    easts = [cell_center(cell.q, cell.r, size)[0] for cell in report.cells] + [0.0]
    norths = [cell_center(cell.q, cell.r, size)[1] for cell in report.cells] + [0.0]
    min_e, max_e = min(easts) - pad, max(easts) + pad
    min_n, max_n = min(norths) - pad, max(norths) + pad
    span_e = max(max_e - min_e, 1e-9)
    span_n = max(max_n - min_n, 1e-9)
    scale = min(_SVG_SIZE / span_e, _SVG_SIZE / span_n)
    off_x = (_SVG_SIZE - span_e * scale) / 2
    off_y = (_SVG_SIZE - span_n * scale) / 2

    def to_x(east: float) -> float:
        return off_x + (east - min_e) * scale

    def to_y(north: float) -> float:
        return off_y + (max_n - north) * scale

    busiest = max((cell.aircraft for cell in report.cells), default=1) or 1
    step = _ring_step(max(report.max_range_km, 1.0))
    radius = step
    parts: list[str] = []
    append = parts.append
    append(
        f'<svg viewBox="0 0 {_SVG_SIZE:.0f} {_SVG_SIZE:.0f}" '
        'class="map" role="img" aria-label="Coverage heat map">'
    )
    append(f'<rect x="0" y="0" width="{_SVG_SIZE:.0f}" height="{_SVG_SIZE:.0f}" fill="#0b1622"/>')
    while radius <= max(report.max_range_km, step) * 1.05:
        cx, cy = to_x(0.0), to_y(0.0)
        ring_px = radius * scale
        append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring_px:.1f}" fill="none" '
            'stroke="#2b3f55" stroke-width="1" stroke-dasharray="4 4"/>'
        )
        append(
            f'<text x="{cx:.1f}" y="{cy - ring_px - 3:.1f}" class="ring" '
            f'text-anchor="middle">{radius:.0f} km</text>'
        )
        radius += step

    stroke_width = max(0.4, 0.02 * scale)
    for cell in report.cells:
        east, north = cell_center(cell.q, cell.r, size)
        points = " ".join(
            f"{to_x(corner_east):.1f},{to_y(corner_north):.1f}"
            for corner_east, corner_north in cell_corners(east, north, size)
        )
        fill = _color(cell.aircraft / busiest)
        tooltip = html.escape(
            f"{cell.aircraft} aircraft, {cell.positions} positions, max {cell.max_range_km:.1f} km",
            quote=True,
        )
        append(
            f'<polygon points="{points}" fill="{fill}" stroke="#0b1622" '
            f'stroke-width="{stroke_width:.2f}"><title>{cell.key} ({cell.lat:.4f}, '
            f"{cell.lon:.4f}) — {tooltip}</title></polygon>"
        )

    cx, cy = to_x(0.0), to_y(0.0)
    append(
        f'<g stroke="#ffffff" stroke-width="1.6"><line x1="{cx - 9:.1f}" y1="{cy:.1f}" '
        f'x2="{cx + 9:.1f}" y2="{cy:.1f}"/><line x1="{cx:.1f}" y1="{cy - 9:.1f}" '
        f'x2="{cx:.1f}" y2="{cy + 9:.1f}"/></g>'
    )
    append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="none" stroke="#ffffff" '
        'stroke-width="1.6"/>'
    )
    append(f'<text x="{cx + 11:.1f}" y="{cy + 4:.1f}" class="rx">receiver</text>')
    append(f'<text x="14" y="{_SVG_SIZE - 14:.0f}" class="legend-label">1 aircraft</text>')
    for index, (offset, _rgb) in enumerate(_COLOR_STOPS):
        x = 14.0 + index * 40.0
        append(
            f'<rect x="{x:.0f}" y="{_SVG_SIZE - 44:.0f}" width="40" height="14" '
            f'fill="{_color(offset)}"/>'
        )
    append(f'<text x="174" y="{_SVG_SIZE - 14:.0f}" class="legend-label">{busiest} aircraft</text>')
    append("</svg>")
    return "".join(parts)


def _report_payload(report: Report) -> dict[str, object]:
    """Machine-readable copy of the report, embedded verbatim in the HTML."""
    return {
        "receiver": {"lat": report.receiver_lat, "lon": report.receiver_lon},
        "cell_km": report.cell_km,
        "period": {"start": _iso(report.start), "end": _iso(report.end)},
        "totals": {
            "positions": report.positions,
            "aircraft": report.aircraft,
            "skipped": report.skipped,
            "cells": len(report.cells),
            "messages_per_hour": round(report.messages_per_hour, 3),
            "max_range_km": round(report.max_range_km, 3),
            "p50_range_km": round(report.p50_range_km, 3),
            "p90_range_km": round(report.p90_range_km, 3),
            "p95_range_km": round(report.p95_range_km, 3),
        },
        "cells": [
            {
                "cell": cell.key,
                "q": cell.q,
                "r": cell.r,
                "lat": round(cell.lat, 6),
                "lon": round(cell.lon, 6),
                "aircraft": cell.aircraft,
                "positions": cell.positions,
                "max_range_km": round(cell.max_range_km, 3),
            }
            for cell in report.cells
        ],
        "sectors": [
            {
                "index": sector.index,
                "start_deg": sector.start_deg,
                "label": sector_label(sector.index),
                "count": sector.count,
                "aircraft": sector.aircraft,
                "max_km": sector.max_km,
                "p50_km": sector.p50_km,
                "p90_km": sector.p90_km,
            }
            for sector in report.sectors
        ],
        "days": [
            {"day": day.day, "positions": day.positions, "aircraft": day.aircraft}
            for day in report.days
        ],
        "altitude": [{"bucket": bucket, "count": count} for bucket, count in report.altitude],
        "best_day": report.best_day.day if report.best_day else None,
        "worst_day": report.worst_day.day if report.worst_day else None,
    }


_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #0b1622; color: #dbe6f2;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; }
h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: .4px; }
h2 { margin: 34px 0 12px; font-size: 18px; color: #9fd0ff; border-bottom: 1px solid #22344a;
  padding-bottom: 6px; }
.meta { margin: 0; color: #8ba3bd; font-size: 13px; }
.map { width: 100%; height: auto; border: 1px solid #22344a; border-radius: 8px; }
.ring { fill: #6d84a1; font-size: 11px; }
.rx { fill: #ffffff; font-size: 12px; }
.legend-label { fill: #8ba3bd; font-size: 12px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid #1c2c40; }
th:first-child, td:first-child { text-align: left; }
th { color: #9fd0ff; font-weight: 600; }
td.bar { text-align: left; width: 55%; }
.bar span { display: block; height: 14px; background: #2f9e8f; border-radius: 3px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.card { background: #11223a; border: 1px solid #22344a; border-radius: 8px; padding: 12px 14px; }
.card b { display: block; font-size: 21px; color: #ffffff; }
.card small { color: #8ba3bd; text-transform: uppercase; letter-spacing: .6px; font-size: 11px; }
footer { margin-top: 30px; color: #6d84a1; font-size: 12px; }
""".strip()


def _summary_cards(report: Report) -> str:
    cards = [
        ("Positions", f"{report.positions:,}"),
        ("Aircraft", f"{report.aircraft:,}"),
        ("Hex cells", f"{len(report.cells):,}"),
        ("Max range", f"{report.max_range_km:.1f} km"),
        ("Messages/hour", f"{report.messages_per_hour:.1f}"),
        ("Best day", report.best_day.day if report.best_day else "-"),
    ]
    return "".join(
        f'<div class="card"><small>{html.escape(label)}</small><b>{html.escape(value)}</b></div>'
        for label, value in cards
    )


def _sector_rows(report: Report) -> str:
    rows = []
    for sector in report.sectors:
        rows.append(
            "<tr>"
            f"<td>{sector_label(sector.index)}</td>"
            f"<td>{sector.count}</td>"
            f"<td>{sector.aircraft}</td>"
            f"<td>{_num(sector.p50_km)}</td>"
            f"<td>{_num(sector.p90_km)}</td>"
            f"<td>{_num(sector.max_km)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _altitude_rows(report: Report) -> str:
    peak = max((count for _bucket, count in report.altitude), default=0) or 1
    rows = []
    for bucket, count in report.altitude:
        width = 100.0 * count / peak
        rows.append(
            f"<tr><td>{html.escape(bucket)}</td><td>{count}</td>"
            f'<td class="bar"><span style="width:{width:.1f}%"></span></td></tr>'
        )
    return "".join(rows)


def _day_rows(report: Report) -> str:
    return (
        "".join(
            f"<tr><td>{day.day}</td><td>{day.positions}</td><td>{day.aircraft}</td></tr>"
            for day in report.days
        )
        or '<tr><td colspan="3">no days recorded</td></tr>'
    )


def _sector_summary(sector: Sector) -> str:
    return f"{sector_label(sector.index)}: {sector.count} positions, {_num(sector.max_km)} km max"


def render_html(report: Report) -> str:
    """One self-contained HTML file: inline CSS, inline SVG, inline JSON data."""
    payload = json.dumps(_report_payload(report), separators=(",", ":")).replace("<", "\\u003c")
    title = f"dump1090-coverage — {report.receiver_lat:.4f}, {report.receiver_lon:.4f}"
    busiest = max(report.sectors, key=lambda sector: (sector.count, sector.max_km or 0.0))
    occupied = _sector_summary(busiest)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<main>
<h1>dump1090 coverage report</h1>
<p class="meta">receiver {report.receiver_lat:.4f}, {report.receiver_lon:.4f} ·
{_iso(report.start)} .. {_iso(report.end)} · {report.hours:.1f} h ·
hex cells {report.cell_km:.1f} km · generated
{datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")}</p>
<div class="cards">{_summary_cards(report)}</div>
<h2>Coverage heat map</h2>
{_heatmap_svg(report)}
<h2>Range by bearing ({SECTOR_DEG:.0f}° sectors)</h2>
<p class="meta">busiest sector: {html.escape(occupied)}</p>
<table>
<thead><tr><th>sector</th><th>positions</th><th>aircraft</th><th>p50 km</th>
<th>p90 km</th><th>max km</th></tr></thead>
<tbody>{_sector_rows(report)}</tbody>
</table>
<h2>Altitude histogram (ft)</h2>
<table>
<thead><tr><th>bucket</th><th>count</th><th></th></tr></thead>
<tbody>{_altitude_rows(report)}</tbody>
</table>
<h2>Daily activity (UTC)</h2>
<table>
<thead><tr><th>day</th><th>positions</th><th>ICAOs</th></tr></thead>
<tbody>{_day_rows(report)}</tbody>
</table>
<footer>Produced by dump1090-coverage — every pixel of this page is embedded in the
file itself; it needs no network. Load the JSON below for scripting.</footer>
</main>
<script id="coverage-data" type="application/json">{payload}</script>
</body>
</html>
"""
