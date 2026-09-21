#!/usr/bin/env python3

# CODE PROVENANCE
# RMOB workflow/format references:
#   https://github.com/rabssm/MeteorRadio/blob/main/src/monthly_rmob.py
#   https://github.com/bolidozor/rmob-export
# The V5 UTC exporter is independently implemented for V5 CSV logs.
# See docs/CODE_PROVENANCE.md.


import csv
import glob
import calendar
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

LOG_DIR = Path("/home/pi/radar_data/Logs")
OUT_DIR = Path("/home/pi/meteorradio-rmob/output")

LOCAL = ZoneInfo("Europe/Warsaw")
UTC = ZoneInfo("UTC")

YEAR = 2026
MONTH = 9
OBSERVER = "MeteorRadio_Station"

counts = Counter()
source_rows = 0
converted_rows = 0

first_utc = None
last_utc = None

files = sorted(
    glob.glob(
        str(LOG_DIR / f"R{YEAR}{MONTH:02d}*.csv")
    )
)

print("SOURCE FILES:", len(files))

for fn in files:

    print(" READ:", Path(fn).name)

    with open(fn, newline="", errors="replace") as f:

        for row in csv.DictReader(f):

            source_rows += 1

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

                local_dt = datetime(
                    int(row["Y"]),
                    int(row["M"]),
                    int(row["D"]),
                    int(row["h"]),
                    int(row["m"]),
                    sec_int,
                    usec,
                    tzinfo=LOCAL,
                )

                utc_dt = local_dt.astimezone(UTC)

            except Exception:
                continue

            if first_utc is None or utc_dt < first_utc:
                first_utc = utc_dt

            if last_utc is None or utc_dt > last_utc:
                last_utc = utc_dt

            if (
                utc_dt.year == YEAR
                and utc_dt.month == MONTH
            ):
                counts[
                    (
                        utc_dt.day,
                        utc_dt.hour,
                    )
                ] += 1

                converted_rows += 1


if first_utc is None:
    raise SystemExit("BRAK POPRAWNYCH REKORDOW")

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

month_name = calendar.month_abbr[MONTH].lower()

txt_name = (
    f"{OBSERVER}_"
    f"{MONTH:02d}{YEAR}"
    f"rmob.TXT"
)

txt_path = OUT_DIR / txt_name

now_utc = datetime.now(UTC)

days_in_month = calendar.monthrange(
    YEAR,
    MONTH
)[1]

with txt_path.open(
    "w",
    newline="\n"
) as out:

    header = month_name + "|"

    for hour in range(24):
        header += f" {hour:02d}h|"

    out.write(header + "\n")

    for day in range(
        1,
        days_in_month + 1
    ):

        line = f" {day:02d}|"

        for hour in range(24):

            hour_start = datetime(
                YEAR,
                MONTH,
                day,
                hour,
                0,
                0,
                tzinfo=UTC,
            )

            if hour_start > now_utc:
                cell = "???"

            elif hour_start < first_utc.replace(
                minute=0,
                second=0,
                microsecond=0
            ):
                cell = "???"

            else:
                cell = str(
                    counts.get(
                        (day, hour),
                        0
                    )
                )

            line += f" {cell:<3}|"

        out.write(line + "\n")


dat_path = OUT_DIR / (
    f"RMOB-{YEAR % 100:02d}"
    f"{MONTH:02d}.DAT"
)

with dat_path.open(
    "w",
    newline="\n"
) as out:

    for day in range(
        1,
        days_in_month + 1
    ):
        for hour in range(24):

            hour_start = datetime(
                YEAR,
                MONTH,
                day,
                hour,
                tzinfo=UTC
            )

            if hour_start > now_utc:
                continue

            if hour_start < first_utc.replace(
                minute=0,
                second=0,
                microsecond=0
            ):
                continue

            value = counts.get(
                (day, hour),
                0
            )

            out.write(
                f"{YEAR % 100:02d}"
                f"{MONTH:02d}"
                f"{day:02d}"
                f"{hour:02d},"
                f"{hour:02d},"
                f"{value}\n"
            )


print()
print("========================================")
print(" RMOB UTC EXPORT")
print("========================================")
print("SOURCE ROWS:   ", source_rows)
print("UTC SEP ROWS:  ", converted_rows)
print("FIRST UTC:     ", first_utc)
print("LAST UTC:      ", last_utc)
print("TXT:           ", txt_path)
print("DAT:           ", dat_path)
print("TOTAL COUNT:   ", sum(counts.values()))
print("========================================")
