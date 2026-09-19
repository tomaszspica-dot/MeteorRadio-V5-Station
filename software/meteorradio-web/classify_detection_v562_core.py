#!/usr/bin/env python3

import json
import sys

from pathlib import Path

import numpy as np

from scipy.signal import (
    stft,
    get_window,
)

from scipy.ndimage import (
    gaussian_filter,
)


NFFT = 2048
OVERLAP = 0.9375
NOOVERLAP = int(NFFT * OVERLAP)

TARGET_IF_HZ = 2000.0


def robust_span(x):

    x = np.asarray(
        x,
        dtype=float,
    )

    x = x[
        np.isfinite(x)
    ]

    if len(x) < 2:
        return 999.0

    return float(
        np.percentile(x, 95)
        -
        np.percentile(x, 5)
    )


def moving_fraction(
    mask,
    n,
):

    n = max(
        1,
        int(n),
    )

    return np.convolve(
        mask.astype(float),
        np.ones(n) / n,
        mode="same",
    )


def main(path):

    path = Path(path)

    with np.load(
        path,
        allow_pickle=False,
    ) as z:

        samples = np.asarray(
            z["samples"]
        )

        fs = float(
            z["sample_rate"]
        )


    # ========================================================
    # STFT
    # ========================================================

    window = get_window(
        "hamming",
        NFFT,
        fftbins=True,
    )


    f, t, Z = stft(
        samples,
        fs=fs,
        window=window,
        nperseg=NFFT,
        noverlap=NOOVERLAP,
        nfft=NFFT,
        detrend=False,
        return_onesided=False,
        boundary=None,
        padded=False,
    )


    f = np.fft.fftshift(
        f
    )

    Z = np.fft.fftshift(
        Z,
        axes=0,
    )


    offset = (
        f
        -
        TARGET_IF_HZ
    )


    display_band = (
        (offset >= -300)
        &
        (offset <= +300)
    )


    freq = offset[
        display_band
    ]


    raw_db = (
        20.0
        *
        np.log10(
            np.abs(
                Z[
                    display_band,
                    :
                ]
            )
            +
            1e-12
        )
    )


    dt = float(
        np.median(
            np.diff(t)
        )
    )


    df = float(
        abs(
            freq[1]
            -
            freq[0]
        )
    )


    # ========================================================
    # PRE BACKGROUND
    # ========================================================

    total_time = float(
        t[-1]
        -
        t[0]
    )


    pre_s = min(
        1.20,
        max(
            0.50,
            total_time * 0.18,
        )
    )


    pre = (
        t
        <=
        t[0] + pre_s
    )


    if np.count_nonzero(pre) >= 4:

        background = np.median(
            raw_db[:, pre],
            axis=1,
        )

    else:

        background = np.percentile(
            raw_db,
            40,
            axis=1,
        )


    rel = (
        raw_db
        -
        background[:, None]
    )


    rel = gaussian_filter(
        rel,
        sigma=(
            0.55,
            0.35,
        ),
    )


    # ========================================================
    # ANCHOR
    #
    # Najmocniejszy punkt w paśmie detekcji.
    # Dla head+trail powinien wypaść blisko połączenia.
    # ========================================================

    detection_band = (
        (freq >= -200)
        &
        (freq <= +200)
    )


    A = rel[
        detection_band,
        :
    ]


    row, anchor_index = np.unravel_index(
        int(
            np.argmax(A)
        ),
        A.shape,
    )


    detection_freq = freq[
        detection_band
    ]


    anchor_time = float(
        t[
            anchor_index
        ]
    )


    anchor_freq = float(
        detection_freq[
            row
        ]
    )


    anchor_peak = float(
        A[
            row,
            anchor_index
        ]
    )


    # ========================================================
    # TRAIL CENTER
    #
    # Nie wybieramy pojedynczego piku.
    # Szukamy częstotliwości, która UTRZYMUJE SIĘ
    # przez kilka sekund po anchor.
    # ========================================================

    trail_search_time = (
        (t >= anchor_time)
        &
        (
            t
            <=
            min(
                float(t[-1]),
                anchor_time + 3.50,
            )
        )
    )


    trail_search_freq = (
        (freq >= anchor_freq - 110)
        &
        (freq <= anchor_freq + 110)
    )


    B = rel[
        trail_search_freq,
        :
    ][
        :,
        trail_search_time
    ]


    persistence = np.mean(
        B >= 5.5,
        axis=1,
    )


    p70 = np.percentile(
        B,
        70,
        axis=1,
    )


    trail_score = (
        7.0 * persistence
        +
        p70
    )


    trail_candidates = freq[
        trail_search_freq
    ]


    trail_center = float(
        trail_candidates[
            int(
                np.argmax(
                    trail_score
                )
            )
        ]
    )


    # ========================================================
    # TRAIL FORWARD
    # ========================================================

    trail_band = (
        (freq >= trail_center - 35)
        &
        (freq <= trail_center + 35)
    )


    trail_data = rel[
        trail_band,
        :
    ]


    trail_trace = np.max(
        trail_data,
        axis=0,
    )


    rolling_window = max(
        3,
        int(
            round(
                0.20
                /
                max(
                    dt,
                    1e-6,
                )
            )
        ),
    )


    trail_persistence = moving_fraction(
        trail_trace >= 6.0,
        rolling_window,
    )


    trail_active = (
        trail_persistence
        >=
        0.45
    )


    trail_start = int(
        anchor_index
    )


    near_anchor = np.flatnonzero(
        trail_active
        &
        (t >= anchor_time - 0.05)
        &
        (t <= anchor_time + 0.25)
    )


    if len(near_anchor):

        trail_start = max(
            anchor_index,
            int(
                near_anchor[0]
            ),
        )


    trail_end = int(
        trail_start
    )


    while (
        trail_end + 1
        <
        len(trail_active)
        and
        trail_active[
            trail_end + 1
        ]
    ):

        trail_end += 1


    trail_matrix = trail_data[
        :,
        trail_start:
        trail_end + 1
    ]


    trail_bins = np.argmax(
        trail_matrix,
        axis=0,
    )


    trail_freq_axis = freq[
        trail_band
    ]


    trail_freq = trail_freq_axis[
        trail_bins
    ]


    trail_strengths = trail_matrix[
        trail_bins,
        np.arange(
            trail_matrix.shape[1]
        ),
    ]


    good_trail = (
        trail_strengths
        >=
        6.0
    )


    if np.count_nonzero(
        good_trail
    ) >= 3:

        trail_stability = robust_span(
            trail_freq[
                good_trail
            ]
        )

        trail_strength = float(
            np.median(
                trail_strengths[
                    good_trail
                ]
            )
        )

        trail_freq_median = float(
            np.median(
                trail_freq[
                    good_trail
                ]
            )
        )

    else:

        trail_stability = 999.0
        trail_strength = 0.0
        trail_freq_median = trail_center


    trail_duration = float(
        t[trail_end]
        -
        t[trail_start]
    )


    # ========================================================
    # HEAD — TRACK BACKWARDS FROM ANCHOR
    # ========================================================

    head_band = (
        (freq >= -200)
        &
        (freq <= +200)
    )


    head_freq_axis = freq[
        head_band
    ]


    H = rel[
        head_band,
        :
    ]


    current_bin = int(
        np.argmin(
            np.abs(
                head_freq_axis
                -
                anchor_freq
            )
        )
    )


    max_back = max(
        10,
        int(
            round(
                0.80
                /
                max(
                    dt,
                    1e-6,
                )
            )
        ),
    )


    track = []


    for time_index in range(
        anchor_index,
        max(
            -1,
            anchor_index - max_back,
        ),
        -1,
    ):

        lo = max(
            0,
            current_bin - 1,
        )

        hi = min(
            len(head_freq_axis),
            current_bin + 4,
        )


        candidates = np.arange(
            lo,
            hi,
        )


        values = H[
            candidates,
            time_index
        ]


        penalties = np.where(
            candidates < current_bin,
            2.0
            *
            (
                current_bin
                -
                candidates
            ),
            0.25
            *
            np.abs(
                candidates
                -
                current_bin
            ),
        )


        best_local = int(
            np.argmax(
                values
                -
                penalties
            )
        )


        best_bin = int(
            candidates[
                best_local
            ]
        )


        strength = float(
            values[
                best_local
            ]
        )


        track.append(
            (
                time_index,
                best_bin,
                strength,
            )
        )


        current_bin = best_bin


    track = track[
        ::-1
    ]


    head_t = np.array(
        [
            t[x[0]]
            for x in track
        ],
        dtype=float,
    )


    head_f = np.array(
        [
            head_freq_axis[
                x[1]
            ]
            for x in track
        ],
        dtype=float,
    )


    head_d = np.array(
        [
            x[2]
            for x in track
        ],
        dtype=float,
    )


    # ========================================================
    # WYBÓR NAJLEPSZEGO ODCINKA HEAD
    #
    # Musi kończyć się w anchor.
    # Oceniamy:
    # - liniowość ścieżki
    # - siłę
    # - ciągłość
    # - excursion
    #
    # Nie zmieniamy progu HEAD 18 dB.
    # ========================================================

    candidates = []


    for start in range(
        len(head_t) - 4
    ):

        duration = float(
            head_t[-1]
            -
            head_t[start]
        )


        if not (
            0.15
            <=
            duration
            <=
            0.80
        ):

            continue


        slope, intercept = np.polyfit(
            head_t[start:],
            head_f[start:],
            1,
        )


        predicted = (
            slope
            *
            head_t[start:]
            +
            intercept
        )


        residual = float(
            np.sum(
                (
                    head_f[start:]
                    -
                    predicted
                )
                **
                2
            )
        )


        total = float(
            np.sum(
                (
                    head_f[start:]
                    -
                    np.mean(
                        head_f[start:]
                    )
                )
                **
                2
            )
        )


        r2 = (
            1.0
            -
            residual
            /
            total
            if total > 0
            else
            0.0
        )


        median_strength = float(
            np.median(
                head_d[start:]
            )
        )


        occupancy = float(
            np.mean(
                head_d[start:]
                >=
                4.5
            )
        )


        excursion = robust_span(
            head_f[start:]
        )


        peak = float(
            np.max(
                head_d[start:]
            )
        )


        score = (
            3.0 * r2
            +
            0.10 * median_strength
            +
            0.50 * occupancy
            +
            0.001 * excursion
        )


        if (
            slope >= -30
            and
            excursion < 30
        ):

            score -= 5.0


        candidates.append(
            (
                score,
                start,
                duration,
                float(slope),
                r2,
                median_strength,
                occupancy,
                excursion,
                peak,
            )
        )


    if not candidates:

        raise RuntimeError(
            "Brak kandydata HEAD"
        )


    best = max(
        candidates,
        key=lambda x:
            x[0]
    )


    (
        _score,
        head_start,
        head_duration,
        head_drift,
        head_r2,
        head_median,
        head_occupancy,
        head_excursion,
        head_peak,
    ) = best


    head_start_sample = int(
        track[
            head_start
        ][0]
    )


    head_start_freq = float(
        head_f[
            head_start
        ]
    )


    head_end_freq = float(
        head_f[-1]
    )


    join = abs(
        head_end_freq
        -
        trail_freq_median
    )


    event_duration = float(
        t[trail_end]
        -
        t[
            head_start_sample
        ]
    )


    # ========================================================
    # SZEROKOŚĆ CHWILOWA
    #
    # Nie mierzymy ruchu meteoru po częstotliwości.
    # Mierzymy szerokość śladu W DANEJ CHWILI.
    # ========================================================

    widths = []


    for (
        time_index,
        bin_index,
        strength
    ) in track[
        head_start:
    ]:

        column = H[
            :,
            time_index
        ]


        cut = max(
            4.5,
            strength - 10.0,
        )


        left = right = int(
            bin_index
        )


        while (
            left > 0
            and
            column[
                left - 1
            ]
            >=
            cut
        ):

            left -= 1


        while (
            right + 1
            <
            len(column)
            and
            column[
                right + 1
            ]
            >=
            cut
        ):

            right += 1


        widths.append(
            (
                right
                -
                left
                +
                1
            )
            *
            df
        )


    for j in range(
        trail_matrix.shape[1]
    ):

        bin_index = int(
            trail_bins[j]
        )

        strength = float(
            trail_strengths[j]
        )


        if strength < 6.0:
            continue


        column = trail_matrix[
            :,
            j
        ]


        cut = max(
            6.0,
            strength - 10.0,
        )


        left = right = bin_index


        while (
            left > 0
            and
            column[
                left - 1
            ]
            >=
            cut
        ):

            left -= 1


        while (
            right + 1
            <
            len(column)
            and
            column[
                right + 1
            ]
            >=
            cut
        ):

            right += 1


        widths.append(
            (
                right
                -
                left
                +
                1
            )
            *
            df
        )


    median_width = float(
        np.median(
            widths
        )
    )


    p90_width = float(
        np.percentile(
            widths,
            90,
        )
    )


    trail_continuity = float(
        np.mean(
            good_trail
        )
    )


    # ========================================================
    # ISTNIEJĄCE PROGI
    # ========================================================

    head_ok = bool(
        head_duration >= 0.15
        and
        head_peak >= 18.0
        and
        (
            abs(
                head_drift
            )
            >=
            30.0
            or
            head_excursion
            >=
            30.0
        )
    )


    trail_ok = bool(
        trail_duration >= 0.35
        and
        trail_strength >= 7.0
        and
        trail_stability <= 45.0
    )


    join_ok = bool(
        join <= 70.0
    )


    peak_ok = bool(
        anchor_peak >= 20.0
    )


    continuity_ok = bool(
        trail_continuity >= 0.72
    )


    result = {

        "shadow_version":
            "v5.6.2-anchor-head-trail",

        "anchor": {

            "time_s":
                round(
                    anchor_time,
                    3,
                ),

            "freq_hz":
                round(
                    anchor_freq,
                    1,
                ),

            "peak_db":
                round(
                    anchor_peak,
                    2,
                ),
        },

        "head": {

            "start_s":
                round(
                    float(
                        t[
                            head_start_sample
                        ]
                    ),
                    3,
                ),

            "duration_s":
                round(
                    head_duration,
                    3,
                ),

            "start_hz":
                round(
                    head_start_freq,
                    1,
                ),

            "end_hz":
                round(
                    head_end_freq,
                    1,
                ),

            "excursion_hz":
                round(
                    head_excursion,
                    1,
                ),

            "drift_hz_per_s":
                round(
                    head_drift,
                    1,
                ),

            "peak_db":
                round(
                    head_peak,
                    2,
                ),

            "r2":
                round(
                    head_r2,
                    3,
                ),

            "occupancy":
                round(
                    head_occupancy,
                    3,
                ),

            "ok_known_thresholds":
                head_ok,
        },

        "trail": {

            "center_hz":
                round(
                    trail_freq_median,
                    1,
                ),

            "duration_s":
                round(
                    trail_duration,
                    3,
                ),

            "stability_hz":
                round(
                    trail_stability,
                    1,
                ),

            "strength_db":
                round(
                    trail_strength,
                    2,
                ),

            "continuity_ratio":
                round(
                    trail_continuity,
                    3,
                ),

            "ok_known_thresholds":
                trail_ok,
        },

        "join": {

            "hz":
                round(
                    join,
                    1,
                ),

            "ok_known_threshold":
                join_ok,
        },

        "event": {

            "duration_s":
                round(
                    event_duration,
                    3,
                ),

            "median_instant_width_hz":
                round(
                    median_width,
                    1,
                ),

            "p90_instant_width_hz":
                round(
                    p90_width,
                    1,
                ),
        },

        "known_flags": {

            "head_echo":
                head_ok,

            "trail":
                trail_ok,

            "join":
                join_ok,

            "peak":
                peak_ok,

            "continuity":
                continuity_ok,
        },
    }


    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":

    main(
        sys.argv[1]
    )
