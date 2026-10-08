"""Command-line interface for dump1090-coverage."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dump1090_coverage import __version__
from dump1090_coverage.analysis import Report, build_report
from dump1090_coverage.errors import CoverageError
from dump1090_coverage.read import Dataset, load
from dump1090_coverage.render import render

EXIT_OK = 0
EXIT_ERROR = 1

FORMATS = ("html", "geojson", "text")

__all__ = ["EXIT_ERROR", "EXIT_OK", "main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dump1090-coverage",
        description=(
            "Analyse a recorded dump1090 / readsb history and render receiver coverage: "
            "a hex-grid heat map, bearing-sector range statistics and traffic totals "
            "as self-contained HTML, GeoJSON or a text table."
        ),
        epilog="Input is a local recording; nothing here contacts a decoder or the network.",
    )
    parser.add_argument(
        "--input",
        "-i",
        metavar="PATH",
        required=True,
        help=(
            "NDJSON export from `dump1090-recorder export --format ndjson` "
            "or a dump1090-recorder SQLite database"
        ),
    )
    parser.add_argument(
        "--sqlite",
        action="store_true",
        help="treat --input as a SQLite database regardless of its extension",
    )
    parser.add_argument(
        "--receiver-lat",
        type=float,
        default=None,
        metavar="DEG",
        help="receiver latitude (read from the recording when possible)",
    )
    parser.add_argument(
        "--receiver-lo",
        type=float,
        default=None,
        metavar="DEG",
        help="receiver longitude (read from the recording when possible)",
    )
    parser.add_argument(
        "--cell-km",
        type=float,
        default=5.0,
        metavar="KM",
        help="point-to-point width of a hex grid cell in kilometres (default: 5)",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="html",
        help="output format (default: html)",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default="-",
        help="output file, or - for stdout (default: -)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _receiver(dataset: Dataset, args: argparse.Namespace) -> tuple[float, float]:
    """Resolve the receiver position: explicit flags first, then the recording."""
    given = (args.receiver_lat, args.receiver_lo)
    if all(value is not None for value in given):
        return float(args.receiver_lat), float(args.receiver_lo)
    if any(value is not None for value in given):
        raise CoverageError("--receiver-lat and --receiver-lo must be given together")
    if dataset.receiver is not None:
        return dataset.receiver
    raise CoverageError(
        "receiver position unknown: the recording has no receiver lat/lon "
        "(pass --receiver-lat and --receiver-lo)"
    )


def _write_stdout(text: str) -> None:
    """Write to stdout as UTF-8 bytes when possible, so glyphs never crash a legacy console."""
    payload = text if text.endswith("\n") else text + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload)
        return
    buffer.write(payload.encode("utf-8"))
    buffer.flush()


def _write(path: str, text: str) -> None:
    if path == "-":
        _write_stdout(text)
        return
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise CoverageError(f"cannot write {path}: {reason}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code (``0`` ok, ``1`` expected failure)."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        dataset = load(args.input, force_sqlite=args.sqlite)
        receiver = _receiver(dataset, args)
        report: Report = build_report(
            dataset.observations,
            receiver_lat=receiver[0],
            receiver_lon=receiver[1],
            cell_km=args.cell_km,
            skipped=dataset.skipped,
        )
        _write(args.out, render(report, args.format))
    except CoverageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    target = "stdout" if args.out == "-" else args.out
    print(
        f"# {report.positions} positions, {report.aircraft} aircraft, "
        f"{len(report.cells)} cells @ {report.cell_km:g} km: {args.format} -> {target}",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
