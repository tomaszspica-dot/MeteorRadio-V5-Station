#!/usr/bin/env python3
"""Generate an RMOB monthly summary JPEG from a standard RMOB text table.

This is an independent MeteorRadio V5 renderer. It does not contain or execute
Colorgramme/Colorgramme Lab code. The layout follows the public RMOB convention:
station information, current/latest day's hourly histogram, and monthly heatmap.
"""

from __future__ import annotations

import argparse
import calendar
import configparser
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


@dataclass(frozen=True)
class StationInfo:
    observer: str
    country: str
    city: str
    longitude: str
    latitude: str
    frequency_hz: str
    antenna: str
    azimuth_deg: str
    elevation_deg: str
    rf_preamplifier: str
    receiver: str
    method: str
    computer: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an RMOB-compatible monthly summary JPEG"
    )
    parser.add_argument(
        "--txt",
        type=Path,
        required=True,
        help="Observer_MMYYYYrmob.TXT",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="RMOB station INI file",
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JPEG path",
    )
    return parser.parse_args()


def load_station(path: Path) -> StationInfo:
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(path):
        raise SystemExit(f"Cannot read configuration: {path}")
    if "station" not in cfg:
        raise SystemExit("Missing [station] section in configuration")

    section = cfg["station"]

    def value(name: str, default: str = "") -> str:
        return section.get(name, default).strip()

    observer = value("observer")
    if not observer:
        raise SystemExit("Missing station.observer")

    return StationInfo(
        observer=observer,
        country=value("country"),
        city=value("city"),
        longitude=value("longitude"),
        latitude=value("latitude"),
        frequency_hz=value("frequency_hz", "143050000"),
        antenna=value("antenna"),
        azimuth_deg=value("azimuth_deg"),
        elevation_deg=value("elevation_deg"),
        rf_preamplifier=value("rf_preamplifier"),
        receiver=value("receiver", "RTL-SDR"),
        method=value("method", "MeteorRadio"),
        computer=value("computer", "Raspberry Pi / Linux"),
    )


def parse_rmob_txt(path: Path, year: int, month: int) -> np.ndarray:
    days_in_month = calendar.monthrange(year, month)[1]
    data = np.full((days_in_month, 24), np.nan, dtype=float)

    lines = path.read_text(errors="replace").splitlines()
    if not lines:
        raise SystemExit(f"Empty RMOB file: {path}")

    header = [part.strip() for part in lines[0].split("|") if part.strip()]
    hours = [cell for cell in header[1:] if cell.lower().endswith("h")]
    if len(hours) != 24:
        raise SystemExit(
            f"Invalid RMOB header: expected 24 hours, got {len(hours)}"
        )

    for line in lines[1:]:
        cells = line.split("|")
        if not cells:
            continue

        try:
            day = int(cells[0].strip())
        except ValueError:
            continue

        if not (1 <= day <= days_in_month):
            continue

        values = cells[1:25]
        for hour, raw in enumerate(values):
            token = raw.strip()
            if token in {"", "???", "---"}:
                continue
            try:
                data[day - 1, hour] = int(token)
            except ValueError:
                continue

    return data


def latest_observed_day(data: np.ndarray) -> int:
    observed = [
        idx + 1
        for idx in range(data.shape[0])
        if np.isfinite(data[idx]).any()
    ]
    if not observed:
        raise SystemExit("No observed hours in RMOB table")
    return observed[-1]


def format_frequency(value: str) -> str:
    try:
        hz = float(value)
    except ValueError:
        return value

    if hz >= 1_000_000:
        return f"{hz / 1_000_000:.6f} MHz"
    if hz >= 1_000:
        return f"{hz / 1_000:.3f} kHz"
    return f"{hz:.0f} Hz"


def render(
    data: np.ndarray,
    station: StationInfo,
    *,
    year: int,
    month: int,
    output: Path,
) -> None:
    latest_day = latest_observed_day(data)
    latest_counts = np.nan_to_num(
        data[latest_day - 1],
        nan=0.0,
    )

    finite_values = data[np.isfinite(data)]
    vmax = max(
        1.0,
        float(np.nanmax(finite_values))
        if finite_values.size
        else 1.0,
    )

    cmap = plt.get_cmap("turbo").copy()
    cmap.set_bad("black")

    fig = plt.figure(figsize=(11.2, 4.4), dpi=100)
    fig.suptitle(
        f"{station.observer} — "
        f"{calendar.month_name[month]} {year} — RMOB",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    grid = fig.add_gridspec(
        2,
        3,
        width_ratios=(1.45, 1.45, 2.7),
        height_ratios=(1.0, 1.0),
        left=0.04,
        right=0.96,
        top=0.88,
        bottom=0.12,
        wspace=0.35,
        hspace=0.42,
    )

    ax_info = fig.add_subplot(grid[:, 0])
    ax_info.axis("off")

    info_lines = [
        ("Observer", station.observer),
        ("Country", station.country),
        ("City", station.city),
        ("Longitude", station.longitude),
        ("Latitude", station.latitude),
        ("Frequency", format_frequency(station.frequency_hz)),
        ("Antenna", station.antenna),
        ("Azimuth", station.azimuth_deg),
        ("Elevation", station.elevation_deg),
        ("RF preamp", station.rf_preamplifier),
        ("Receiver", station.receiver),
        ("Obs. method", station.method),
        ("Computer", station.computer),
    ]

    y = 0.98
    for label, value in info_lines:
        if not value:
            continue
        ax_info.text(
            0.0,
            y,
            f"{label}:",
            fontweight="bold",
            fontsize=8.5,
            va="top",
        )
        ax_info.text(
            0.34,
            y,
            value,
            fontsize=8.5,
            va="top",
            wrap=True,
        )
        y -= 0.072

    ax_hist = fig.add_subplot(grid[:, 1])
    ax_hist.bar(
        np.arange(24),
        latest_counts,
        width=0.78,
    )
    ax_hist.set_title(
        f"{calendar.month_name[month]} {latest_day}, {year}\n"
        "Hourly counts (UTC)",
        fontsize=10,
    )
    ax_hist.set_xlabel("Hour UTC", fontsize=8)
    ax_hist.set_ylabel("Count", fontsize=8)
    ax_hist.set_xticks(np.arange(0, 24, 4))
    ax_hist.tick_params(labelsize=8)
    ax_hist.grid(axis="y", alpha=0.25)

    ax_heat = fig.add_subplot(grid[:, 2])
    masked = np.ma.masked_invalid(data.T)
    image = ax_heat.imshow(
        masked,
        origin="upper",
        aspect="auto",
        interpolation="nearest",
        cmap=cmap,
        vmin=0,
        vmax=vmax,
    )
    ax_heat.set_title("Monthly hourly counts", fontsize=10)
    ax_heat.set_xlabel("Day of month", fontsize=8)
    ax_heat.set_ylabel("Hour UTC", fontsize=8)
    ax_heat.set_xticks(np.arange(0, data.shape[0], 2))
    ax_heat.set_xticklabels(
        np.arange(1, data.shape[0] + 1, 2)
    )
    ax_heat.set_yticks(np.arange(0, 24, 3))
    ax_heat.set_yticklabels(np.arange(0, 24, 3))
    ax_heat.tick_params(labelsize=7)

    cbar = fig.colorbar(
        image,
        ax=ax_heat,
        fraction=0.035,
        pad=0.025,
    )
    cbar.set_label("Hourly count", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    fig.text(
        0.5,
        0.035,
        "MeteorRadio V5 RMOB summary — independent renderer "
        "(not Colorgramme/Colorgramme Lab)",
        ha="center",
        fontsize=7.5,
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    fig.savefig(
        output,
        format="jpeg",
        dpi=100,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={
            "quality": 92,
            "optimize": True,
        },
    )
    plt.close(fig)


def main() -> None:
    args = parse_args()
    station = load_station(args.config)
    data = parse_rmob_txt(
        args.txt,
        args.year,
        args.month,
    )

    output = (
        args.output
        or args.txt.with_name(
            f"{station.observer}_{args.month:02d}{args.year}.jpg"
        )
    )

    render(
        data,
        station,
        year=args.year,
        month=args.month,
        output=output,
    )

    print("RMOB_JPEG=", output)
    print("RMOB_JPEG_SIZE=", output.stat().st_size)


if __name__ == "__main__":
    main()
