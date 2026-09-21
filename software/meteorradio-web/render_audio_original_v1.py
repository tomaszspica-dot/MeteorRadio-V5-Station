#!/usr/bin/env python3

# CODE PROVENANCE
# Method reference:
#   rabssm/MeteorRadio src/smp2wav.py
#   https://github.com/rabssm/MeteorRadio/blob/main/src/smp2wav.py
# The core method (real component of complex IQ -> signed 16-bit PCM for USB)
# is adapted/reimplemented here with V5 validation and atomic output handling.
# See docs/CODE_PROVENANCE.md.


# MR_AUDIO_ORIGINAL_V1
#
# Niefiltrowany USB WAV z zapisanego SMP complex IQ.
#
# BRAK:
# - band-pass
# - noise gate
# - normalizacji
# - fade
# - odszumiania
#
# To jest materiał do samodzielnej obróbki.
#
# Źródłem pozostaje zapisane complex IQ SMP.

import os
import sys
import wave

from pathlib import Path

import numpy as np


if len(sys.argv) != 3:

    raise SystemExit(
        "usage: render_audio_original_v1.py "
        "INPUT.npz OUTPUT.wav"
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
# Dokładnie niefiltrowana reprezentacja USB:
# real(complex IQ).
#
audio_real=np.real(
    samples
).astype(
    np.float32,
    copy=False,
)


audio_real=np.nan_to_num(
    audio_real,
    nan=0.0,
    posinf=0.0,
    neginf=0.0,
)


#
# Brak normalizacji.
#
# Zapisujemy amplitudę wynikającą bezpośrednio
# z SMP tak jak w klasycznym smp2wav MeteorRadio.
#
pcm=(
    audio_real
    *
    32767.0
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
                round(
                    sample_rate
                )
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
    "ORIGINAL_USB_WAV=PASS",
    f"rate={int(round(sample_rate))}",
    f"frames={pcm.size}",
    f"duration={pcm.size/sample_rate:.3f}s",
    f"bytes={DST.stat().st_size}",
)
