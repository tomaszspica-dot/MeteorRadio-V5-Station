#!/usr/bin/env python3

# CODE PROVENANCE
# Base IQ-to-USB-audio method reference:
#   rabssm/MeteorRadio src/smp2wav.py
#   https://github.com/rabssm/MeteorRadio/blob/main/src/smp2wav.py
# This V5 implementation is rewritten and extends the method with station-local
# band-pass filtering, DC removal, normalization and click-reducing fades.
# See docs/CODE_PROVENANCE.md.


# MR_AUDIO_RENDER_V4_BANDPASS
#
# MeteorRadio SMP -> USB WAV
#
# Zachowujemy:
#   - ton GRAVES ~2 kHz
#   - Doppler
#
# Redukujemy:
#   - szum poniżej 1.4 kHz
#   - szum powyżej 2.6 kHz
#
# Bez noise-gate:
# nie chcemy obcinać słabych meteor trails.

import os
import sys
import wave

from pathlib import Path

import numpy as np

from scipy.signal import (
    butter,
    sosfiltfilt,
)


LOW_HZ = 1400.0
HIGH_HZ = 2600.0
FILTER_ORDER = 6


if len(sys.argv) != 3:
    raise SystemExit(
        "usage: render_audio_v1.py INPUT.npz OUTPUT.wav"
    )


SRC=Path(sys.argv[1])
DST=Path(sys.argv[2])


if not SRC.is_file():
    raise SystemExit(
        f"input missing: {SRC}"
    )


DST.parent.mkdir(
    parents=True,
    exist_ok=True,
)


with np.load(
    SRC,
    allow_pickle=False,
) as z:

    samples=np.asarray(
        z["samples"]
    ).reshape(-1)

    sample_rate=float(
        np.asarray(
            z["sample_rate"]
        ).reshape(-1)[0]
    )


if not np.iscomplexobj(samples):

    raise RuntimeError(
        "samples are not complex IQ"
    )


if (
    not np.isfinite(sample_rate)
    or
    sample_rate < 8000
    or
    sample_rate > 192000
):

    raise RuntimeError(
        f"invalid sample rate: {sample_rate}"
    )


if samples.size < 100:

    raise RuntimeError(
        "too few samples"
    )


#
# Awaryjny limit długości.
#
max_samples=int(
    sample_rate * 30.0
)

if samples.size > max_samples:

    samples=samples[
        :max_samples
    ]


#
# USB:
# real(complex IQ)
#
audio=np.real(
    samples
).astype(
    np.float32,
    copy=False,
)


audio=np.nan_to_num(
    audio,
    nan=0.0,
    posinf=0.0,
    neginf=0.0,
)


#
# DC removal.
#
audio -= np.float32(
    np.mean(
        audio,
        dtype=np.float64,
    )
)


#
# GRAVES USB BAND-PASS.
#
# 2 kHz zostaje w środku.
#
# +/- 600 Hz zapasu pozwala zachować
# słyszalne zmiany częstotliwości Dopplera.
#
sos=butter(
    FILTER_ORDER,
    [
        LOW_HZ,
        HIGH_HZ,
    ],
    btype="bandpass",
    fs=sample_rate,
    output="sos",
)


#
# Zero-phase offline filtering.
# Nie przesuwa czasowo ani częstotliwościowo
# śladu Dopplera.
#
audio=sosfiltfilt(
    sos,
    audio,
).astype(
    np.float32,
    copy=False,
)


#
# Ponowne usunięcie minimalnego DC
# po filtracji.
#
audio -= np.float32(
    np.mean(
        audio,
        dtype=np.float64,
    )
)


#
# Normalizacja odsłuchowa.
#
level=float(
    np.quantile(
        np.abs(audio),
        0.999,
    )
)


if (
    not np.isfinite(level)
    or
    level < 1e-12
):

    level=float(
        np.max(
            np.abs(audio)
        )
    )


if (
    np.isfinite(level)
    and
    level > 1e-12
):

    audio *= (
        0.82 / level
    )


audio=np.clip(
    audio,
    -0.98,
    0.98,
)


#
# 10 ms fade przeciw trzaskom.
#
fade_n=min(
    int(
        sample_rate * 0.010
    ),
    audio.size // 2,
)


if fade_n > 1:

    fade=np.linspace(
        0.0,
        1.0,
        fade_n,
        dtype=np.float32,
    )

    audio[:fade_n] *= fade
    audio[-fade_n:] *= fade[::-1]


pcm=np.rint(
    audio * 32767.0
).astype(
    "<i2"
)


tmp=DST.with_name(
    DST.name
    +
    f".tmp-{os.getpid()}"
)


try:

    with wave.open(
        str(tmp),
        "wb",
    ) as w:

        w.setnchannels(1)
        w.setsampwidth(2)

        w.setframerate(
            int(
                round(sample_rate)
            )
        )

        w.writeframes(
            pcm.tobytes()
        )


    os.replace(
        tmp,
        DST
    )


finally:

    try:
        tmp.unlink()

    except FileNotFoundError:
        pass


print(
    "AUDIO_USB_BANDPASS=PASS",
    f"rate={int(round(sample_rate))}",
    f"band={LOW_HZ:.0f}-{HIGH_HZ:.0f}Hz",
    f"frames={pcm.size}",
    f"duration={pcm.size/sample_rate:.3f}s",
    f"bytes={DST.stat().st_size}",
)
