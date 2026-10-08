"""Shared fixtures: the committed sample recording, loaded and aggregated."""

from __future__ import annotations

from pathlib import Path

import pytest

from dump1090_coverage.analysis import Report, build_report
from dump1090_coverage.read import Dataset, load
from helpers import RECEIVER_HINT_NDJSON, RECEIVER_LAT, RECEIVER_LON, SAMPLE_NDJSON


@pytest.fixture
def sample_path() -> Path:
    """Path of the committed NDJSON sample (21 positions, 6 aircraft, 3 days)."""
    return SAMPLE_NDJSON


@pytest.fixture
def hint_path() -> Path:
    """Path of the tiny recording that carries the receiver position inline."""
    return RECEIVER_HINT_NDJSON


@pytest.fixture
def sample_dataset(sample_path: Path) -> Dataset:
    """The sample recording, read from disk."""
    return load(sample_path)


@pytest.fixture
def sample_report(sample_dataset: Dataset) -> Report:
    """The sample recording aggregated with 5 km hex cells."""
    return build_report(
        sample_dataset.observations,
        receiver_lat=RECEIVER_LAT,
        receiver_lon=RECEIVER_LON,
        cell_km=5.0,
        skipped=sample_dataset.skipped,
    )
