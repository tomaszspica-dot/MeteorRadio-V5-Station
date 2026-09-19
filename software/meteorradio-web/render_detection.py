#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from scipy.signal import (
    ShortTimeFFT,
)

from scipy.signal.windows import (
    hamming,
)


if len(sys.argv) != 3:
    raise SystemExit(
        "usage: render_detection.py INPUT.npz OUTPUT.png"
    )


SRC = Path(sys.argv[1])
DST = Path(sys.argv[2])


if not SRC.exists():
    raise SystemExit(
        f"brak pliku: {SRC}"
    )


DST.parent.mkdir(
    parents=True,
    exist_ok=True,
)


with np.load(
    SRC,
    allow_pickle=False,
) as z:

    samples = np.asarray(
        z["samples"]
    )

    sample_rate = float(
        z["sample_rate"]
    )

    centre_freq = float(
        z["centre_freq"]
    )


if samples.size < 4096:
    raise SystemExit(
        "za mało próbek"
    )


# ============================================================
# PARAMETRY WIZUALIZACJI
#
# Tryb zbliżony do MeteorRadio --headecho:
#
# FFT      2048
# overlap  93.75 %
# Hamming
#
# Pozwala pokazać krótkie zdarzenie znacznie czytelniej.
# ============================================================

NFFT = 2048

OVERLAP = 0.9375

HOP = int(
    NFFT
    * (
        1.0
        - OVERLAP
    )
)

window = hamming(
    NFFT,
    sym=True,
)


sft = ShortTimeFFT(
    window,
    hop=HOP,
    fs=sample_rate,
    mfft=NFFT,
    fft_mode="centered",
)


Pxx = sft.spectrogram(
    samples
)

times = sft.t(
    len(samples)
)

baseband_hz = sft.f


# MeteorRadio stroi SDR 2 kHz poniżej
# częstotliwości GRAVES.
#
# Dlatego:
#
# baseband +2000 Hz == 143.050 MHz
#
offset_hz = (
    baseband_hz
    - 2000.0
)


# ============================================================
# TYLKO ±300 Hz
# ============================================================

freq_mask = (
    (offset_hz >= -300.0)
    &
    (offset_hz <= 300.0)
)

offset = offset_hz[
    freq_mask
]

power = Pxx[
    freq_mask,
    :
]


if (
    offset.size == 0
    or
    power.size == 0
):
    raise SystemExit(
        "brak danych w paśmie ±500 Hz"
    )


db = 10.0 * np.log10(
    np.maximum(
        power,
        1e-20,
    )
)


# ============================================================
# AUTOMATYCZNIE ZNAJDŹ MOMENT ZDARZENIA
#
# Szukamy największego sygnału w paśmie ±200 Hz.
# ============================================================

detect_mask = (
    np.abs(offset)
    <= 200.0
)


if np.any(
    detect_mask
):

    event_trace = np.max(
        db[
            detect_mask,
            :
        ],
        axis=0,
    )

else:

    event_trace = np.max(
        db,
        axis=0,
    )


peak_time_index = int(
    np.argmax(
        event_trace
    )
)

peak_time = float(
    times[
        peak_time_index
    ]
)


# ============================================================
# ZOOM CZASOWY
#
# Z 10-sekundowego SMP pokazujemy około 4 sekundy
# wokół faktycznego zdarzenia.
# ============================================================

DISPLAY_SECONDS = 4.0

t_min_all = float(
    times[0]
)

t_max_all = float(
    times[-1]
)


if (
    t_max_all
    - t_min_all
    <= DISPLAY_SECONDS
):

    view_start = t_min_all
    view_end = t_max_all

else:

    view_start = (
        peak_time
        - 1.5
    )

    view_end = (
        view_start
        + DISPLAY_SECONDS
    )

    if view_start < t_min_all:

        view_start = t_min_all

        view_end = (
            view_start
            + DISPLAY_SECONDS
        )

    if view_end > t_max_all:

        view_end = t_max_all

        view_start = (
            view_end
            - DISPLAY_SECONDS
        )


time_mask = (
    (times >= view_start)
    &
    (times <= view_end)
)


view_times = times[
    time_mask
]

view_power = power[
    :,
    time_mask
]

view_db = db[
    :,
    time_mask
]


if view_db.size == 0:
    raise SystemExit(
        "brak danych po zoomie czasu"
    )


# ============================================================
# GLOBALNA SKALA WODOSPADU
#
# NIE odejmujemy już mediany osobno od każdej kolumny.
#
# To właśnie powodowało kolorowy szum.
# ============================================================

noise_floor = float(
    np.percentile(
        view_db,
        50.0,
    )
)

vmin = (
    noise_floor
    + 2.0
)

vmax = float(
    np.percentile(
        view_db,
        99.8,
    )
)


# Minimalny sensowny zakres kontrastu.
if vmax < (
    vmin
    + 16.0
):

    vmax = (
        vmin
        + 18.0
    )


# Nie pozwalamy pojedynczemu ekstremalnemu pikowi
# zniszczyć kontrastu całego obrazu.
if vmax > (
    vmin
    + 40.0
):

    vmax = (
        vmin
        + 30.0
    )


# ============================================================
# SPECTRUM DETEKCJI
#
# AVG + MAX HOLD.
# ============================================================

avg_linear = np.mean(
    view_power,
    axis=1,
)

max_linear = np.max(
    view_power,
    axis=1,
)


avg_db = 10.0 * np.log10(
    np.maximum(
        avg_linear,
        1e-20,
    )
)

max_db = 10.0 * np.log10(
    np.maximum(
        max_linear,
        1e-20,
    )
)


spectrum_reference = float(
    np.median(
        avg_db
    )
)


avg_rel = (
    avg_db
    - spectrum_reference
)

max_rel = (
    max_db
    - spectrum_reference
)


# Delikatne wygładzenie AVG.
kernel = (
    np.ones(
        5,
        dtype=float,
    )
    / 5.0
)

avg_rel_smooth = np.convolve(
    avg_rel,
    kernel,
    mode="same",
)


# ============================================================
# RYSOWANIE
# ============================================================

fig = plt.figure(
    figsize=(
        11.4,
        7.4,
    ),
    dpi=120,
)


fig.patch.set_facecolor(
    "#111820"
)


grid = fig.add_gridspec(
    2,
    1,
    height_ratios=[
        1.0,
        4.0,
    ],
    hspace=0.28,
)


# ------------------------------------------------------------
# GÓRNY WYKRES — SPECTRUM
# ------------------------------------------------------------

ax1 = fig.add_subplot(
    grid[0]
)

ax1.set_facecolor(
    "#070b0f"
)


ax1.plot(
    offset,
    avg_rel_smooth,
    linewidth=1.1,
    color="#62c7ea",
    label="średnia",
)


ax1.plot(
    offset,
    max_rel,
    linewidth=0.85,
    color="#ffb347",
    alpha=0.9,
    label="max-hold",
)


# tylko granice pasma detekcji
for x in (
    -200,
    200,
):

    ax1.axvline(
        x,
        linewidth=0.7,
        color="#41d479",
        alpha=0.85,
    )


ax1.set_xlim(
    -300,
    300,
)


ax1.set_ylabel(
    "dB ponad tło",
    color="#aab7c4",
    fontsize=8,
)


ax1.set_title(
    "Spectrum detekcji — średnia + max-hold",
    color="#e0e8ef",
    fontsize=9,
    loc="left",
)


ax1.tick_params(
    colors="#91a0ae",
    labelsize=7,
)


ax1.legend(
    loc="upper right",
    fontsize=7,
    facecolor="#111820",
    edgecolor="#354452",
    labelcolor="#d8e1e9",
)


ax1.grid(
    alpha=0.12,
)


for spine in ax1.spines.values():

    spine.set_color(
        "#354452"
    )


# ------------------------------------------------------------
# DOLNY WYKRES — WATERFALL
# ------------------------------------------------------------

ax2 = fig.add_subplot(
    grid[1]
)

ax2.set_facecolor(
    "#070b0f"
)


mesh = ax2.pcolormesh(
    view_times,
    offset,
    view_db,
    shading="auto",
    cmap="inferno",
    vmin=vmin,
    vmax=vmax,
    rasterized=True,
)


for y in (
    -200,
    200,
):

    ax2.axhline(
        y,
        linewidth=0.7,
        color="#41d479",
        alpha=0.85,
    )


ax2.set_ylim(
    -300,
    300,
)


ax2.set_xlim(
    view_start,
    view_end,
)


ax2.set_xlabel(
    "czas od początku zapisu [s]",
    color="#aab7c4",
    fontsize=8,
)


ax2.set_ylabel(
    "offset od 143.050 MHz [Hz]",
    color="#aab7c4",
    fontsize=8,
)


ax2.tick_params(
    colors="#91a0ae",
    labelsize=7,
)


ax2.set_title(
    (
        "Waterfall detekcji"
        f" · zoom wokół zdarzenia {peak_time:.2f} s"
        " · zielone = ±200 Hz"
    ),
    color="#e0e8ef",
    fontsize=9,
    loc="left",
)


for spine in ax2.spines.values():

    spine.set_color(
        "#354452"
    )


cbar = fig.colorbar(
    mesh,
    ax=ax2,
    pad=0.012,
    fraction=0.025,
)


cbar.set_label(
    "moc [dB]",
    color="#aab7c4",
    fontsize=8,
)


cbar.ax.tick_params(
    colors="#91a0ae",
    labelsize=7,
)


fig.suptitle(
    (
        SRC.name
        + "  ·  FFT 2048"
        + "  ·  overlap 93.75%"
    ),
    color="#dce4ec",
    fontsize=8,
    x=0.08,
    ha="left",
)


fig.subplots_adjust(
    left=0.075,
    right=0.94,
    top=0.92,
    bottom=0.09,
)


fig.savefig(
    DST,
    facecolor=fig.get_facecolor(),
)


plt.close(
    fig
)


print(
    DST
)
