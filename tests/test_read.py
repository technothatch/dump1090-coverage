"""Input readers: NDJSON parsing, SQLite parsing, format detection, error paths."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dump1090_coverage.errors import InputError
from dump1090_coverage.read import SQLITE_MAGIC, detect_format, load
from helpers import make_sqlite, write_ndjson


def test_loads_the_sample_recording(sample_path: Path) -> None:
    dataset = load(sample_path)
    assert dataset.source == "ndjson"
    assert len(dataset.observations) == 21
    assert dataset.skipped == 1
    assert dataset.receiver is None
    assert dataset.start == 1790812800.0
    assert dataset.end == 1790985600.0
    assert {obs.hex for obs in dataset.observations} == {
        "abc123",
        "def456",
        "4ca918",
        "40621d",
        "3c4f8a",
        "780abc",
    }


def test_hex_addresses_are_normalised_to_lower_case(tmp_path: Path) -> None:
    path = write_ndjson(
        tmp_path / "case.ndjson",
        [{"t": 1.0, "aircraft": [{"hex": " 4CA918 ", "lat": 51.5, "lon": -0.4}]}],
    )
    dataset = load(path)
    assert dataset.observations[0].hex == "4ca918"


def test_flight_is_trimmed(tmp_path: Path) -> None:
    path = write_ndjson(
        tmp_path / "flight.ndjson",
        [{"t": 1.0, "aircraft": [{"hex": "abc123", "flight": "BAW117  ", "lat": 1.0, "lon": 2.0}]}],
    )
    dataset = load(path)
    assert dataset.observations[0].flight == "BAW117"


def test_altitude_falls_back_to_alt_geom(tmp_path: Path) -> None:
    path = write_ndjson(
        tmp_path / "geom.ndjson",
        [
            {
                "t": 1.0,
                "aircraft": [
                    {"hex": "aaaaaa", "alt_geom": 30000, "lat": 1.0, "lon": 2.0},
                    {"hex": "bbbbbb", "lat": 1.0, "lon": 2.0},
                    {"hex": "cccccc", "alt_baro": "ground", "lat": 1.0, "lon": 2.0},
                ],
            }
        ],
    )
    dataset = load(path)
    assert dataset.observations[0].alt_ft == 30000.0
    assert dataset.observations[1].alt_ft is None
    assert dataset.observations[2].alt_ft == 0.0


def test_receiver_is_read_from_a_top_level_record(hint_path: Path) -> None:
    dataset = load(hint_path)
    assert dataset.receiver == (51.47, -0.45)
    assert len(dataset.observations) == 2


def test_receiver_is_read_from_a_nested_object(tmp_path: Path) -> None:
    path = write_ndjson(
        tmp_path / "nested.ndjson",
        [
            {"receiver": {"lat": 48.2, "lon": 16.3}},
            {"t": 1.0, "aircraft": [{"hex": "abc123", "lat": 48.3, "lon": 16.4}]},
        ],
    )
    dataset = load(path)
    assert dataset.receiver == (48.2, 16.3)


def test_invalid_json_reports_the_line_number(tmp_path: Path) -> None:
    path = tmp_path / "broken.ndjson"
    path.write_text('{"t": 1, "aircraft": []}\nnot json\n', encoding="utf-8")
    with pytest.raises(InputError, match=r"broken\.ndjson:2: invalid JSON"):
        load(path)


def test_record_without_timestamp_is_rejected(tmp_path: Path) -> None:
    path = write_ndjson(tmp_path / "notime.ndjson", [{"aircraft": []}])
    with pytest.raises(InputError, match="needs a numeric 't'"):
        load(path)


def test_unrecognised_record_is_rejected(tmp_path: Path) -> None:
    path = write_ndjson(tmp_path / "odd.ndjson", [{"hello": "world"}])
    with pytest.raises(InputError, match="neither"):
        load(path)


def test_line_that_is_not_an_object_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.ndjson"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(InputError, match="expected a JSON object"):
        load(path)


def test_blank_lines_and_bad_entries_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "gaps.ndjson"
    path.write_text(
        "\n"
        '{"t": 1.0, "aircraft": ["nonsense", {"hex": "nope"}]}\n'
        "\n"
        '{"t": 2.0, "aircraft": [{"hex": "aaaaaa", "lat": 51.5, "lon": -0.4}]}\n',
        encoding="utf-8",
    )
    dataset = load(path)
    assert len(dataset.observations) == 1
    assert dataset.skipped == 2


def test_out_of_range_coordinates_are_skipped(tmp_path: Path) -> None:
    path = write_ndjson(
        tmp_path / "far.ndjson",
        [{"t": 1.0, "aircraft": [{"hex": "aaaaaa", "lat": 95.0, "lon": 12.0}]}],
    )
    with pytest.raises(InputError, match="no position observations"):
        load(path)


def test_missing_input_file(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="input not found"):
        load(tmp_path / "nope.ndjson")


def test_input_directory_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="not a file"):
        load(tmp_path)


def test_empty_input_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.ndjson"
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(InputError, match="no position observations"):
        load(path)


def test_non_utf8_input_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "binary.ndjson"
    path.write_bytes(b"\xff\xfe\x00bad\n")
    with pytest.raises(InputError, match="UTF-8"):
        load(path)


def test_detect_format_defaults_to_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "flight.ndjson"
    path.write_text("{}", encoding="utf-8")
    assert detect_format(path) == "ndjson"


def test_detect_format_by_extension(tmp_path: Path) -> None:
    for name in ("rec.sqlite", "rec.sqlite3", "rec.db", "rec.DB"):
        path = tmp_path / name
        path.write_text("", encoding="utf-8")
        assert detect_format(path) == "sqlite"


def test_detect_format_by_magic_bytes_beats_extension(tmp_path: Path) -> None:
    path = tmp_path / "recording.dat"
    path.write_bytes(SQLITE_MAGIC + b"\x00" * 32)
    assert detect_format(path) == "sqlite"
    assert detect_format(path, force_sqlite=True) == "sqlite"


def test_detect_format_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="cannot read"):
        detect_format(tmp_path / "absent.ndjson")


def test_sqlite_database_round_trip(tmp_path: Path) -> None:
    path = make_sqlite(
        tmp_path / "recording.sqlite",
        [
            (1790812800.0, "ABC123", "BAW117", 51.5, -0.4, "12000"),
            (1790812860.0, "def456", None, 51.6, -0.3, "ground"),
            (1790812920.0, "abc123", "BAW117", 51.7, -0.2, 34000),
            (1790812980.0, "nope", None, None, None, "1000"),
        ],
    )
    dataset = load(path)
    assert dataset.source == "sqlite"
    assert len(dataset.observations) == 3
    assert dataset.skipped == 1
    assert dataset.observations[0].hex == "abc123"
    assert dataset.observations[0].alt_ft == 12000.0
    assert dataset.observations[1].alt_ft == 0.0
    assert dataset.observations[2].alt_ft == 34000.0
    assert dataset.observations[1].flight is None


def test_sqlite_receiver_table_is_read(tmp_path: Path) -> None:
    path = make_sqlite(
        tmp_path / "withreceiver.sqlite",
        [(1.0, "abc123", None, 51.5, -0.4, 12000)],
        receiver=(51.47, -0.45),
    )
    dataset = load(path)
    assert dataset.receiver == (51.47, -0.45)


def test_sqlite_without_positions_table(tmp_path: Path) -> None:
    path = tmp_path / "other.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE flights (hex TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(InputError, match="no 'positions' table"):
        load(path)


def test_sqlite_positions_table_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "partial.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE positions (ts REAL, lat REAL)")
    connection.commit()
    connection.close()
    with pytest.raises(InputError, match="missing column"):
        load(path)


def test_sqlite_receiver_table_without_coordinates(tmp_path: Path) -> None:
    path = make_sqlite(
        tmp_path / "nocoords.sqlite",
        [(1.0, "abc123", None, 51.5, -0.4, 12000)],
        receiver=None,
    )
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE receiver (ts REAL)")
    connection.commit()
    connection.close()
    assert load(path).receiver is None


def test_sqlite_with_no_usable_rows(tmp_path: Path) -> None:
    path = make_sqlite(tmp_path / "empty.sqlite", [(1.0, None, None, None, None, None)])
    with pytest.raises(InputError, match="no position observations"):
        load(path)


def test_forcing_sqlite_on_an_ndjson_file(sample_path: Path) -> None:
    with pytest.raises(InputError, match="SQLite"):
        load(sample_path, force_sqlite=True)


def test_sample_entries_match_the_recorded_json(sample_path: Path) -> None:
    raw = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines()]
    assert len(raw) == 6
    assert all("t" in record and "aircraft" in record for record in raw)
