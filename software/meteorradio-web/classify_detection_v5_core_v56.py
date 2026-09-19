#!/usr/bin/env python3

import json
import sys
from pathlib import Path

import numpy as np

from scipy.signal import (
    ShortTimeFFT,
)

from scipy.signal.windows import (
    hamming,
)


def result(
    **kwargs
):

    print(
        json.dumps(
            kwargs,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )
    )


if len(
    sys.argv
) != 2:

    result(
        ok=False,
        error="usage",
    )

    raise SystemExit(
        2
    )


src = Path(
    sys.argv[1]
)


if not src.exists():

    result(
        ok=False,
        error="file not found",
    )

    raise SystemExit(
        1
    )


try:

    with np.load(
        src,
        allow_pickle=False,
    ) as z:

        samples = np.asarray(
            z["samples"]
        )

        sample_rate = float(
            z["sample_rate"]
        )


    nfft = 2048
    hop = 128

    window = hamming(
        nfft,
        sym=True,
    )


    stft = ShortTimeFFT(
        window,
        hop=hop,
        fs=sample_rate,
        mfft=nfft,
        fft_mode="centered",
    )


    pxx = stft.spectrogram(
        samples
    )

    times = stft.t(
        len(
            samples
        )
    )

    baseband = stft.f


    #
    # To samo przeliczenie offsetu,
    # którego używa obecny renderer.
    #
    offsets = (
        baseband
        - 2000.0
    )


    mask = (
        (offsets >= -300.0)
        &
        (offsets <= 300.0)
    )

    offsets = offsets[
        mask
    ]

    pxx = pxx[
        mask,
        :
    ]


    db = 10.0 * np.log10(
        np.maximum(
            pxx,
            1e-20,
        )
    )


    detect = (
        np.abs(
            offsets
        )
        <= 200.0
    )

    db_det = db[
        detect,
        :
    ]

    off_det = offsets[
        detect
    ]


    floor = float(
        np.percentile(
            db_det,
            50.0,
        )
    )

    peak = float(
        np.max(
            db_det
        )
    )

    peak_margin = (
        peak
        - floor
    )


    threshold = (
        floor
        +
        max(
            6.0,
            min(
                11.0,
                peak_margin
                * 0.38,
            ),
        )
    )


    column_peak = np.max(
        db_det,
        axis=0,
    )

    active = (
        column_peak
        >
        threshold
    )


    idx = np.flatnonzero(
        active
    )


    if idx.size < 2:

        result(
            ok=True,
            kind="uncertain",
            label="niepewne",
            confidence=25,
            explanation=(
                "Za mało punktów ponad "
                "lokalnym progiem."
            ),
            metrics={
                "peak_over_floor_db":
                    round(
                        peak_margin,
                        2,
                    ),
            },
        )

        raise SystemExit(
            0
        )


    active_times = times[
        idx
    ]


    duration = max(
        float(
            active_times[-1]
            - active_times[0]
        ),
        hop
        / sample_rate,
    )


    det_active = db_det[
        :,
        idx
    ]


    peak_bins = np.argmax(
        det_active,
        axis=0,
    )

    track = off_det[
        peak_bins
    ]


    freq_span = float(
        np.percentile(
            track,
            95,
        )
        -
        np.percentile(
            track,
            5,
        )
    )


    if (
        len(
            active_times
        )
        >= 3
        and
        float(
            np.ptp(
                active_times
            )
        )
        > 0
    ):

        slope = float(
            np.polyfit(
                active_times,
                track,
                1,
            )[0]
        )

        drift_change = (
            slope
            * duration
        )

    else:

        slope = 0.0
        drift_change = 0.0


    above = (
        det_active
        >
        threshold
    )

    broadband_occupancy = float(
        np.median(
            np.mean(
                above,
                axis=0,
            )
        )
    )


    #
    # To jest HEURYSTYKA,
    # nie automatyczne potwierdzenie meteoru.
    #
    kind = "uncertain"
    label = "niepewne"
    confidence = 40
    explanation = (
        "Kształt nie spełnia wyraźnie "
        "jednego profilu."
    )


    if (
        broadband_occupancy
        >= 0.30
        or
        freq_span
        >= 185.0
    ):

        kind = "interference"
        label = "zakłócenie"
        confidence = int(
            min(
                95,
                65
                +
                broadband_occupancy
                * 70,
            )
        )

        explanation = (
            "Sygnał zajmuje szeroki "
            "fragment pasma."
        )


    elif (
        duration
        >= 1.0
        and
        abs(
            drift_change
        )
        >= 50.0
        and
        freq_span
        >= 40.0
    ):

        kind = "aircraft"
        label = "aircraft scatter"
        confidence = int(
            min(
                95,
                60
                +
                abs(
                    drift_change
                )
                / 4.0,
            )
        )

        explanation = (
            "Długi ślad ze zmianą "
            "częstotliwości w czasie."
        )


    elif (
        duration
        >= 5.5
        and
        freq_span
        < 18.0
        and
        abs(
            drift_change
        )
        < 12.0
    ):

        kind = "interference"
        label = "zakłócenie"
        confidence = 70

        explanation = (
            "Bardzo długi, prawie "
            "nieruchomy wąski sygnał."
        )


    elif (
        peak_margin
        >= 8.0
        and
        broadband_occupancy
        < 0.22
    ):

        kind = "meteor"
        label = "kandydat meteor"
        confidence = int(
            min(
                95,
                55
                +
                min(
                    30,
                    peak_margin,
                )
                +
                (
                    8
                    if freq_span
                    < 100
                    else 0
                ),
            )
        )

        explanation = (
            "Lokalny, stosunkowo wąski "
            "ślad o wyraźnym maksimum."
        )


    result(
        ok=True,
        kind=kind,
        label=label,
        confidence=confidence,
        explanation=explanation,
        metrics={
            "active_duration_s":
                round(
                    duration,
                    2,
                ),
            "peak_over_floor_db":
                round(
                    peak_margin,
                    2,
                ),
            "frequency_span_hz":
                round(
                    freq_span,
                    1,
                ),
            "drift_hz":
                round(
                    drift_change,
                    1,
                ),
            "drift_hz_per_s":
                round(
                    slope,
                    1,
                ),
            "broadband_occupancy":
                round(
                    broadband_occupancy,
                    3,
                ),
        },
    )


except Exception as e:

    result(
        ok=False,
        error=repr(
            e
        ),
    )

    raise
