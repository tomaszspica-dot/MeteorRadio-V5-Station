#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use(
    "Agg"
)

import matplotlib.pyplot as plt

from scipy.signal import (
    ShortTimeFFT,
)

from scipy.signal.windows import (
    hamming,
)


if len(
    sys.argv
) < 3:

    raise SystemExit(
        "usage: "
        "render_detection_v5.py "
        "INPUT.npz OUTPUT.png "
        "[maxhold 0|1]"
    )


SRC = Path(
    sys.argv[1]
)

DST = Path(
    sys.argv[2]
)

MAX_HOLD = True

if len(
    sys.argv
) >= 4:

    MAX_HOLD = (
        str(
            sys.argv[3]
        ).strip()
        != "0"
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

    try:

        obs_time = str(
            z["obs_time"]
        )

    except Exception:

        obs_time = ""


    # MR_FULL_SMP_REAL_TRIGGER_V1
    try:

        trigger_time_meta = str(
            z["trigger_time"]
        )

    except Exception:

        trigger_time_meta = ""


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
    len(
        samples
    )
)

baseband_hz = sft.f


#
# Zachowujemy przeliczenie
# obecnego renderera MeteorRadio.
#
offset_hz = (
    baseband_hz
    - 2000.0
)


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


db = 10.0 * np.log10(
    np.maximum(
        power,
        1e-20,
    )
)


detect_mask = (
    np.abs(
        offset
    )
    <= 200.0
)


event_trace = np.max(
    db[
        detect_mask,
        :
    ],
    axis=0,
)


peak_i = int(
    np.argmax(
        event_trace
    )
)

peak_time = float(
    times[
        peak_i
    ]
)


# MR_FULL_SMP_REAL_TRIGGER_V1
#
# Renderer nie przycina już danych wokół maksimum sygnału.
# Pokazujemy CAŁY materiał zapisany przez Adaptive Capture.
#

t_min = float(
    times[0]
)

t_max = float(
    times[-1]
)


view_start = t_min
view_end = t_max


#
# Domyślnie fallbackiem jest peak_time.
# Dla nowych Adaptive Capture korzystamy jednak
# z prawdziwego trigger_time zapisanego w NPZ.
#

trigger_plot_time = peak_time
trigger_source = "PEAK-FALLBACK"


if (
    trigger_time_meta
    and
    obs_time
):

    try:

        trigger_plot_time = float(
            (
                np.datetime64(
                    trigger_time_meta
                )
                -
                np.datetime64(
                    obs_time
                )
            )
            /
            np.timedelta64(
                1,
                "s"
            )
        )

        if not (
            t_min
            <=
            trigger_plot_time
            <=
            t_max
        ):

            trigger_plot_time = peak_time
            trigger_source = "PEAK-FALLBACK"

        else:

            trigger_source = "NPZ-TRIGGER"

    except Exception:

        trigger_plot_time = peak_time
        trigger_source = "PEAK-FALLBACK"


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


vmax = max(
    vmax,
    vmin
    + 18.0,
)

vmax = min(
    vmax,
    vmin
    + 30.0,
)


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


reference = float(
    np.median(
        avg_db
    )
)

avg_rel = (
    avg_db
    - reference
)

max_rel = (
    max_db
    - reference
)


kernel = (
    np.ones(
        5
    )
    / 5.0
)

avg_rel = np.convolve(
    avg_rel,
    kernel,
    mode="same",
)


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


ax1 = fig.add_subplot(
    grid[0]
)

ax1.set_facecolor(
    "#070b0f"
)


ax1.plot(
    offset,
    avg_rel,
    linewidth=1.15,
    color="#62c7ea",
    label="średnia",
)


if MAX_HOLD:

    ax1.plot(
        offset,
        max_rel,
        linewidth=0.85,
        color="#ffb347",
        alpha=0.9,
        label="max-hold",
    )


for x in (
    -200,
    200,
):

    pass  # MR_REMOVE_AX1_TRIGGER_LINE_FINAL


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
    (
        "Spectrum detekcji — "
        "średnia"
        +
        (
            " + max-hold"
            if MAX_HOLD
            else ""
        )
    ),
    color="#e0e8ef",
    fontsize=9,
    loc="left",
)

ax1.tick_params(
    colors="#91a0ae",
    labelsize=7,
)

ax1.grid(
    alpha=0.12,
)

ax1.legend(
    loc="upper right",
    fontsize=7,
    facecolor="#111820",
    edgecolor="#354452",
    labelcolor="#d8e1e9",
)

for spine in ax1.spines.values():

    spine.set_color(
        "#354452"
    )


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


#
# Prawdziwy moment triggera zapisany w NPZ.
# Dla starego SMP bez metadata fallback = peak_time.
#
pass  # MR_REMOVE_AX2_TRIGGER_LINE_FINAL


pass  # MR_REMOVE_AX2_AXVSPAN_V1


pass  # MR_REMOVE_AX2_TEXT_V1


ax2.set_xlim(
    view_start,
    view_end,
)

ax2.set_ylim(
    -300,
    300,
)

ax2.set_xlabel(
    (
        "czas od początku zapisu [s]   "
        "PRE "
        f"{trigger_plot_time-view_start:.2f}s"
        "  |  TRIGGER  |  POST "
        f"{view_end-trigger_plot_time:.2f}s"
    ),
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
        f" · trigger {trigger_plot_time:.2f} s"
        f" [{trigger_source}]"
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
        + " · "
        + obs_time
        + " · FFT 2048"
        + " · overlap 93.75%"
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
