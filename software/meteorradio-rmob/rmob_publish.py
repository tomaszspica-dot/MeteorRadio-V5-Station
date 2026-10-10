#!/usr/bin/env python3
"""Generate RMOB TXT/DAT + JPEG and optionally upload the pair."""

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    now = datetime.now(UTC)

    parser = argparse.ArgumentParser(
        description="MeteorRadio V5 RMOB publish pipeline"
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--year",
        type=int,
        default=now.year,
    )
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        default=now.month,
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
    )
    parser.add_argument(
        "--dry-run-upload",
        action="store_true",
    )

    return parser.parse_args()


def load_config(
    path: Path,
) -> tuple[
    configparser.SectionProxy,
    configparser.SectionProxy,
]:

    cfg = configparser.ConfigParser(
        interpolation=None
    )

    if not cfg.read(path):
        raise SystemExit(
            f"Cannot read configuration: {path}"
        )

    if (
        "station" not in cfg
        or "paths" not in cfg
    ):
        raise SystemExit(
            "Configuration must contain "
            "[station] and [paths]"
        )

    return (
        cfg["station"],
        cfg["paths"],
    )


def run(
    command: list[str],
) -> None:

    print(
        "+",
        " ".join(command),
    )

    completed = subprocess.run(
        command,
        check=False,
    )

    if completed.returncode != 0:
        raise SystemExit(
            completed.returncode
        )


def main() -> None:
    args = parse_args()

    (
        station,
        paths,
    ) = load_config(
        args.config
    )

    observer = station.get(
        "observer",
        "",
    ).strip()

    if not observer:
        raise SystemExit(
            "Missing station.observer"
        )

    log_dir = Path(
        paths.get(
            "log_dir",
            "/home/pi/radar_data/Logs",
        )
    )

    out_dir = Path(
        paths.get(
            "out_dir",
            "/home/pi/meteorradio-rmob/output",
        )
    )

    source_timezone = paths.get(
        "source_timezone",
        "UTC",
    ).strip()

    client = Path(
        paths.get(
            "uploader",
            "/home/pi/meteorradio-rmob/RMOBclient_arm64",
        )
    )

    txt = (
        out_dir
        / (
            f"{observer}_"
            f"{args.month:02d}{args.year}"
            f"rmob.TXT"
        )
    )

    jpg = (
        out_dir
        / (
            f"{observer}_"
            f"{args.month:02d}{args.year}"
            f".jpg"
        )
    )

    run(
        [
            sys.executable,
            str(
                HERE
                / "rmob_utc_export.py"
            ),
            "--year",
            str(args.year),
            "--month",
            str(args.month),
            "--observer",
            observer,
            "--log-dir",
            str(log_dir),
            "--out-dir",
            str(out_dir),
            "--source-timezone",
            source_timezone,
        ]
    )

    run(
        [
            sys.executable,
            str(
                HERE
                / "rmob_colorgramme.py"
            ),
            "--txt",
            str(txt),
            "--config",
            str(args.config),
            "--year",
            str(args.year),
            "--month",
            str(args.month),
            "--output",
            str(jpg),
        ]
    )

    if args.no_upload:
        print(
            "RMOB_UPLOAD_SKIPPED=YES"
        )
        return

    command = [
        sys.executable,
        str(
            HERE
            / "rmob_upload.py"
        ),
        "--client",
        str(client),
        "--txt",
        str(txt),
        "--jpg",
        str(jpg),
    ]

    if args.dry_run_upload:
        command.append(
            "--dry-run"
        )

    run(command)


if __name__ == "__main__":
    main()
