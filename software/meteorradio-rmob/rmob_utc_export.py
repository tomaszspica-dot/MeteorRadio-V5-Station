#!/usr/bin/env python3
"""Export MeteorRadio daily CSV detections to monthly RMOB TXT/DAT files.

The upstream MeteorRadio CSV timestamps are naive. Their source timezone is
therefore an explicit input so hourly bins can be converted to UTC without
changing acquisition.
"""

from __future__ import annotations

# CODE PROVENANCE
# RMOB workflow/format references:
#   https://github.com/rabssm/MeteorRadio/blob/main/src/monthly_rmob.py
#   https://github.com/bolidozor/rmob-export
# The V5 UTC exporter is independently implemented for V5 CSV logs.
# See docs/CODE_PROVENANCE.md.

import argparse
import calendar
import csv
import glob
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_LOG_DIR = Path("/home/pi/radar_data/Logs")
DEFAULT_OUT_DIR = Path("/home/pi/meteorradio-rmob/output")


def parse_args() -> argparse.Namespace:
    now = datetime.now(UTC)

    parser = argparse.ArgumentParser(
        description="Export MeteorRadio counts in RMOB UTC format"
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
        "--observer",
        default=os.environ.get(
            "RMOB_OBSERVER",
            "MeteorRadio_Station",
        ),
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
    )
    parser.add_argument(
        "--source-timezone",
        default=os.environ.get(
            "RMOB_SOURCE_TIMEZONE",
            "UTC",
        ),
        help=(
            "Timezone used by naive MeteorRadio CSV timestamps, "
            "for example UTC or Europe/Warsaw"
        ),
    )

    return parser.parse_args()


def row_to_utc(
    row: dict[str, str],
    source_tz: ZoneInfo,
) -> datetime | None:
    try:
        sec = float(row["s"])
        sec_int = int(sec)
        usec = int(
            round(
                (sec - sec_int)
                * 1_000_000
            )
        )

        if usec >= 1_000_000:
            sec_int += 1
            usec -= 1_000_000

        source_dt = datetime(
            int(row["Y"]),
            int(row["M"]),
            int(row["D"]),
            int(row["h"]),
            int(row["m"]),
            sec_int,
            usec,
            tzinfo=source_tz,
        )

        return source_dt.astimezone(UTC)

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def collect_counts(
    log_dir: Path,
    year: int,
    month: int,
    source_tz: ZoneInfo,
) -> tuple[
    Counter[tuple[int, int]],
    int,
    int,
    datetime | None,
    datetime | None,
]:
    counts: Counter[tuple[int, int]] = Counter()

    source_rows = 0
    converted_rows = 0

    first_utc: datetime | None = None
    last_utc: datetime | None = None

    # UTC month boundaries can fall on an adjacent local calendar day.
    # Read the requested source-month files plus one neighbouring day on
    # each side, then filter every row after timezone conversion.
    month_start = datetime(
        year,
        month,
        1,
        tzinfo=UTC,
    )

    if month == 12:
        next_month_start = datetime(
            year + 1,
            1,
            1,
            tzinfo=UTC,
        )
    else:
        next_month_start = datetime(
            year,
            month + 1,
            1,
            tzinfo=UTC,
        )

    previous_day = (
        month_start
        - timedelta(days=1)
    )

    candidate_patterns = [
        f"R{year}{month:02d}*.csv",
        (
            "R"
            + previous_day.strftime("%Y%m%d")
            + "*.csv"
        ),
        (
            "R"
            + next_month_start.strftime("%Y%m%d")
            + "*.csv"
        ),
    ]

    file_set: set[str] = set()

    for pattern in candidate_patterns:
        file_set.update(
            glob.glob(
                str(
                    log_dir
                    / pattern
                )
            )
        )

    files = sorted(file_set)

    print(
        "SOURCE FILES:",
        len(files),
    )

    for fn in files:
        path = Path(fn)

        print(
            " READ:",
            path.name,
        )

        with path.open(
            newline="",
            errors="replace",
        ) as handle:

            for row in csv.DictReader(handle):
                source_rows += 1

                utc_dt = row_to_utc(
                    row,
                    source_tz,
                )

                if utc_dt is None:
                    continue

                if (
                    first_utc is None
                    or utc_dt < first_utc
                ):
                    first_utc = utc_dt

                if (
                    last_utc is None
                    or utc_dt > last_utc
                ):
                    last_utc = utc_dt

                if (
                    utc_dt.year == year
                    and utc_dt.month == month
                ):
                    counts[
                        (
                            utc_dt.day,
                            utc_dt.hour,
                        )
                    ] += 1

                    converted_rows += 1

    return (
        counts,
        source_rows,
        converted_rows,
        first_utc,
        last_utc,
    )


def write_rmob_files(
    counts: Counter[tuple[int, int]],
    *,
    year: int,
    month: int,
    observer: str,
    out_dir: Path,
    first_utc: datetime,
    now_utc: datetime | None = None,
) -> tuple[Path, Path]:

    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    now_utc = (
        now_utc
        or datetime.now(UTC)
    )

    days_in_month = calendar.monthrange(
        year,
        month,
    )[1]

    month_name = calendar.month_abbr[
        month
    ].lower()

    txt_path = (
        out_dir
        / (
            f"{observer}_"
            f"{month:02d}{year}"
            f"rmob.TXT"
        )
    )

    first_hour = first_utc.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    with txt_path.open(
        "w",
        newline="\n",
    ) as out:

        header = (
            month_name
            + "|"
            + "".join(
                f" {hour:02d}h|"
                for hour in range(24)
            )
        )

        out.write(
            header
            + "\n"
        )

        for day in range(
            1,
            days_in_month + 1,
        ):
            line = f" {day:02d}|"

            for hour in range(24):

                hour_start = datetime(
                    year,
                    month,
                    day,
                    hour,
                    tzinfo=UTC,
                )

                if (
                    hour_start > now_utc
                    or hour_start < first_hour
                ):
                    cell = "???"
                else:
                    cell = str(
                        counts.get(
                            (
                                day,
                                hour,
                            ),
                            0,
                        )
                    )

                line += (
                    f" {cell:<3}|"
                )

            out.write(
                line
                + "\n"
            )

    dat_path = (
        out_dir
        / (
            f"RMOB-"
            f"{year % 100:02d}"
            f"{month:02d}"
            f".DAT"
        )
    )

    with dat_path.open(
        "w",
        newline="\n",
    ) as out:

        for day in range(
            1,
            days_in_month + 1,
        ):
            for hour in range(24):

                hour_start = datetime(
                    year,
                    month,
                    day,
                    hour,
                    tzinfo=UTC,
                )

                if (
                    hour_start > now_utc
                    or hour_start < first_hour
                ):
                    continue

                value = counts.get(
                    (
                        day,
                        hour,
                    ),
                    0,
                )

                out.write(
                    f"{year % 100:02d}"
                    f"{month:02d}"
                    f"{day:02d}"
                    f"{hour:02d},"
                    f"{hour:02d},"
                    f"{value}"
                    "\n"
                )

    return (
        txt_path,
        dat_path,
    )


def run_export(
    args: argparse.Namespace,
) -> tuple[Path, Path]:

    source_tz = ZoneInfo(
        args.source_timezone
    )

    (
        counts,
        source_rows,
        converted_rows,
        first_utc,
        last_utc,
    ) = collect_counts(
        args.log_dir,
        args.year,
        args.month,
        source_tz,
    )

    if first_utc is None:
        raise SystemExit(
            "NO VALID RECORDS"
        )

    (
        txt_path,
        dat_path,
    ) = write_rmob_files(
        counts,
        year=args.year,
        month=args.month,
        observer=args.observer,
        out_dir=args.out_dir,
        first_utc=first_utc,
    )

    print()
    print(
        "========================================"
    )
    print(
        " RMOB UTC EXPORT"
    )
    print(
        "========================================"
    )
    print(
        "SOURCE TIMEZONE:",
        args.source_timezone,
    )
    print(
        "SOURCE ROWS:   ",
        source_rows,
    )
    print(
        "UTC MONTH ROWS:",
        converted_rows,
    )
    print(
        "FIRST UTC:     ",
        first_utc,
    )
    print(
        "LAST UTC:      ",
        last_utc,
    )
    print(
        "TXT:           ",
        txt_path,
    )
    print(
        "DAT:           ",
        dat_path,
    )
    print(
        "TOTAL COUNT:   ",
        sum(
            counts.values()
        ),
    )
    print(
        "========================================"
    )

    return (
        txt_path,
        dat_path,
    )


def main() -> None:
    run_export(
        parse_args()
    )


if __name__ == "__main__":
    main()
