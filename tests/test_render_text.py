"""The text renderer: a plain-ASCII summary table for terminals and scripts."""

from __future__ import annotations

import re

from dump1090_coverage.analysis import Report
from dump1090_coverage.render import render_text


def test_text_headline_statistics(sample_report: Report) -> None:
    text = render_text(sample_report)
    assert text.startswith("dump1090-coverage summary")
    assert "receiver       51.4700, -0.4500" in text
    assert "cell size      5.0 km" in text
    assert "positions      21 in" in text
    assert "unique ICAOs   6" in text
    assert "skipped rows   1" in text
    assert "messages/hour  0.4" in text


def test_text_shows_the_recorded_period(sample_report: Report) -> None:
    text = render_text(sample_report)
    assert "2026-10-01T00:00:00Z .. 2026-10-03T00:00:00Z" in text
    assert "(48.0 h)" in text


def test_text_has_one_row_per_bearing_sector(sample_report: Report) -> None:
    rows = re.findall(r"^  \d{3}-\d{3} ", render_text(sample_report), flags=re.MULTILINE)
    assert len(rows) == 36


def test_text_marks_empty_sectors_with_a_dash(sample_report: Report) -> None:
    text = render_text(sample_report)
    empty_rows = [
        line
        for line in text.splitlines()
        if line.startswith("  ") and line[2:5].isdigit() and "     -" in line
    ]
    assert empty_rows
    assert any("020-030" in line for line in empty_rows)


def test_text_histogram_counts_add_up(sample_report: Report) -> None:
    text = render_text(sample_report)
    counts = re.findall(r"^  (?:\d+-\d+|40000\+|unknown) +(\d+)$", text, flags=re.MULTILINE)
    assert len(counts) == 12
    assert sum(int(count) for count in counts) == 21


def test_text_lists_every_day_and_best_worst(sample_report: Report) -> None:
    text = render_text(sample_report)
    assert "best day       2026-10-01 (6 ICAOs, 12 positions)" in text
    assert "worst day      2026-10-03 (2 ICAOs, 2 positions)" in text
    assert re.search(r"^  2026-10-02 +7 +6$", text, flags=re.MULTILINE)


def test_text_output_is_ascii_and_newline_terminated(sample_report: Report) -> None:
    text = render_text(sample_report)
    text.encode("ascii")  # must not raise: safe for any console code page
    assert text.endswith("\n")


def test_text_includes_all_range_percentiles(sample_report: Report) -> None:
    text = render_text(sample_report)
    assert "range (km)     max 300.0 | p50" in text
    assert "p90" in text and "p95" in text
