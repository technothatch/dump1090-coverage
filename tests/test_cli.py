"""The CLI: flags, receiver resolution, exit codes and output files."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from dump1090_coverage.cli import main
from helpers import make_sqlite

FLAGS = [
    "--input",
    "--sqlite",
    "--receiver-lat",
    "--receiver-lo",
    "--cell-km",
    "--format",
    "--out",
    "--version",
]


def run(capsys: Any, args: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI and return (exit code, stdout, stderr)."""
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version_flag_prints_and_exits_zero(capsys: Any) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    captured = capsys.readouterr()
    assert excinfo.value.code == 0
    assert "dump1090-coverage 0.1.0" in captured.out


def test_help_documents_every_flag(capsys: Any) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    captured = capsys.readouterr()
    assert excinfo.value.code == 0
    for flag in FLAGS:
        assert flag in captured.out


def test_input_is_mandatory(capsys: Any) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_text_output_to_stdout(sample_path: Path, capsys: Any) -> None:
    code, out, err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--format",
            "text",
        ],
    )
    assert code == 0
    assert "dump1090-coverage summary" in out
    assert "unique ICAOs   6" in out
    assert "21 positions, 6 aircraft" in err
    assert "text -> stdout" in err


def test_html_written_to_a_file(sample_path: Path, tmp_path: Path, capsys: Any) -> None:
    target = tmp_path / "coverage.html"
    code, out, err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--format",
            "html",
            "--out",
            str(target),
        ],
    )
    assert code == 0
    assert out == ""
    document = target.read_text(encoding="utf-8")
    assert document.startswith("<!DOCTYPE html>")
    assert "https://" not in document
    assert f"html -> {target}" in err


def test_geojson_written_to_a_file(sample_path: Path, tmp_path: Path, capsys: Any) -> None:
    target = tmp_path / "coverage.geojson"
    code, _out, _err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--format",
            "geojson",
            "--out",
            str(target),
        ],
    )
    assert code == 0
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["type"] == "FeatureCollection"
    assert document["properties"]["positions"] == 21


def test_default_format_is_html(sample_path: Path, tmp_path: Path, capsys: Any) -> None:
    target = tmp_path / "default.html"
    code, _out, _err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--out",
            str(target),
        ],
    )
    assert code == 0
    assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_receiver_position_read_from_the_recording(hint_path: Path, capsys: Any) -> None:
    code, out, _err = run(capsys, ["--input", str(hint_path), "--format", "text"])
    assert code == 0
    assert "receiver       51.4700, -0.4500" in out


def test_missing_receiver_position_fails_clearly(sample_path: Path, capsys: Any) -> None:
    code, _out, err = run(capsys, ["--input", str(sample_path), "--format", "text"])
    assert code == 1
    assert "receiver position unknown" in err
    assert "--receiver-lat and --receiver-lo" in err


def test_half_a_receiver_position_fails(sample_path: Path, capsys: Any) -> None:
    code, _out, err = run(
        capsys, ["--input", str(sample_path), "--receiver-lat", "51.47", "--format", "text"]
    )
    assert code == 1
    assert "must be given together" in err


def test_missing_input_file(tmp_path: Path, capsys: Any) -> None:
    code, _out, err = run(
        capsys,
        ["--input", str(tmp_path / "nope.ndjson"), "--receiver-lat", "1", "--receiver-lo", "2"],
    )
    assert code == 1
    assert "input not found" in err


def test_empty_input_fails(tmp_path: Path, capsys: Any) -> None:
    empty = tmp_path / "empty.ndjson"
    empty.write_text("\n", encoding="utf-8")
    code, _out, err = run(
        capsys, ["--input", str(empty), "--receiver-lat", "51.47", "--receiver-lo", "-0.45"]
    )
    assert code == 1
    assert "no position observations" in err


def test_invalid_cell_size_fails(sample_path: Path, capsys: Any) -> None:
    code, _out, err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--cell-km",
            "0",
        ],
    )
    assert code == 1
    assert "--cell-km" in err


def test_forced_sqlite_on_ndjson_fails(sample_path: Path, capsys: Any) -> None:
    code, _out, err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--sqlite",
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
        ],
    )
    assert code == 1
    assert "SQLite" in err


def test_sqlite_input_end_to_end(tmp_path: Path, capsys: Any) -> None:
    database = make_sqlite(
        tmp_path / "recording.sqlite",
        [
            (1790812800.0, "abc123", "BAW117", 51.5, -0.4, 12000),
            (1790812900.0, "def456", None, 51.6, -0.3, "ground"),
            (1790813000.0, "abc123", None, 51.7, -0.2, 30000),
        ],
        receiver=(51.47, -0.45),
    )
    code, out, err = run(capsys, ["--input", str(database), "--format", "text"])
    assert code == 0
    assert "unique ICAOs   2" in out
    assert "3 positions" in err


def test_unwritable_output_fails(sample_path: Path, tmp_path: Path, capsys: Any) -> None:
    target = tmp_path / "missing-dir" / "coverage.html"
    code, _out, err = run(
        capsys,
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--out",
            str(target),
        ],
    )
    assert code == 1
    assert "cannot write" in err


def test_unknown_format_is_rejected(sample_path: Path, capsys: Any) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--input",
                str(sample_path),
                "--receiver-lat",
                "1",
                "--receiver-lo",
                "2",
                "--format",
                "png",
            ]
        )
    assert excinfo.value.code == 2


def test_stdout_falls_back_when_there_is_no_buffer(
    sample_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    sink = io.StringIO()
    monkeypatch.setattr(sys, "stdout", sink)
    code = main(
        [
            "--input",
            str(sample_path),
            "--receiver-lat",
            "51.47",
            "--receiver-lo",
            "-0.45",
            "--format",
            "text",
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert "dump1090-coverage summary" in sink.getvalue()


def test_cell_size_flag_changes_the_grid(sample_path: Path, tmp_path: Path, capsys: Any) -> None:
    outputs = []
    for cell_km in ("5", "50"):
        target = tmp_path / f"coverage-{cell_km}.geojson"
        code, _out, _err = run(
            capsys,
            [
                "--input",
                str(sample_path),
                "--receiver-lat",
                "51.47",
                "--receiver-lo",
                "-0.45",
                "--cell-km",
                cell_km,
                "--format",
                "geojson",
                "--out",
                str(target),
            ],
        )
        assert code == 0
        outputs.append(json.loads(target.read_text(encoding="utf-8"))["features"])
    assert len(outputs[1]) < len(outputs[0])
