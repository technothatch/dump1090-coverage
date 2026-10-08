"""The HTML renderer: self-contained output with embedded data and no network."""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from dump1090_coverage.analysis import Report
from dump1090_coverage.render import render, render_html

DATA_RE = r'<script id="coverage-data" type="application/json">(.*?)</script>'


def embedded_payload(document: str) -> dict[str, object]:
    """Parse the JSON blob the HTML page embeds for offline scripting."""
    match = re.search(DATA_RE, document, flags=re.DOTALL)
    assert match is not None, "no embedded coverage-data script"
    payload: dict[str, object] = json.loads(match.group(1))
    return payload


def test_html_is_a_complete_document(sample_report: Report) -> None:
    document = render_html(sample_report)
    assert document.startswith("<!DOCTYPE html>")
    assert document.rstrip().endswith("</html>")
    assert "<style>" in document
    assert "<title>dump1090-coverage" in document


def test_html_references_no_network_resources(sample_report: Report) -> None:
    document = render_html(sample_report)
    assert "http://" not in document
    assert "https://" not in document
    assert "<link" not in document
    assert "src=" not in document
    assert "@import" not in document
    assert "integrity=" not in document


def test_html_embeds_the_report_as_json(sample_report: Report) -> None:
    payload = embedded_payload(render_html(sample_report))
    assert payload["totals"]["positions"] == sample_report.positions == 21
    assert payload["totals"]["aircraft"] == sample_report.aircraft == 6
    assert payload["cell_km"] == 5.0
    assert payload["receiver"] == {"lat": 51.47, "lon": -0.45}
    assert len(payload["cells"]) == len(sample_report.cells)
    assert len(payload["sectors"]) == 36
    assert payload["days"][0]["day"] == "2026-10-01"
    assert payload["best_day"] == "2026-10-01"
    assert payload["worst_day"] == "2026-10-03"


def test_html_embedded_cells_match_the_report(sample_report: Report) -> None:
    payload = embedded_payload(render_html(sample_report))
    cells = payload["cells"]
    first = cells[0]  # type: ignore[index]
    expected = sample_report.cells[0]
    assert first["cell"] == expected.key
    assert first["aircraft"] == expected.aircraft
    assert first["positions"] == expected.positions


def test_html_draws_one_hexagon_per_cell(sample_report: Report) -> None:
    document = render_html(sample_report)
    assert document.count("<polygon") == len(sample_report.cells)
    assert document.count("<svg") == 1


def test_html_contains_every_sector_label(sample_report: Report) -> None:
    document = render_html(sample_report)
    assert "000-010" in document
    assert "180-190" in document
    assert "350-360" in document


def test_html_contains_histogram_and_daily_tables(sample_report: Report) -> None:
    document = render_html(sample_report)
    for label in ("0-999", "40000+", "unknown", "30000-34999"):
        assert label in document
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        assert day in document
    assert document.count("<table") == 3


def test_html_escapes_the_receiver_into_the_title(sample_report: Report) -> None:
    document = render_html(replace(sample_report, receiver_lat=-33.86, receiver_lon=151.21))
    assert "-33.8600, 151.2100" in document
    assert "http" not in document


def test_render_dispatches_every_format(sample_report: Report) -> None:
    assert render(sample_report, "html").startswith("<!DOCTYPE html>")
    assert "dump1090-coverage summary" in render(sample_report, "text")
    assert render(sample_report, "geojson").startswith("{")


def test_render_rejects_unknown_format(sample_report: Report) -> None:
    with pytest.raises(ValueError, match="unknown format"):
        render(sample_report, "pdf")
