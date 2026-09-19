#!/usr/bin/env python3
# V56_STRICT_HEAD_TRAIL_CLASSIFIER

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from scipy.signal import ShortTimeFFT
from scipy.signal.windows import hamming


CORE = Path(__file__).with_name(
    "classify_detection_v5_core_v56.py"
)

VERSION = "v5.6-strict-head-trail"


def emit(data):
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":")
        )
    )


def run_core(path):

    result = subprocess.run(
        [
            sys.executable,
            str(CORE),
            str(path)
        ],
        capture_output=True,
        text=True,
        timeout=90
    )

    if result.returncode != 0:
        raise RuntimeError(
            "core classifier: "
            +
            result.stderr[-1000:]
        )

    text=result.stdout.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    for line in reversed(
        text.splitlines()
    ):
        line=line.strip()

        if (
            line.startswith("{")
            and
            line.endswith("}")
        ):
            return json.loads(line)

    raise RuntimeError(
        "core nie zwrócił JSON"
    )


def robust_span(values):

    values=np.asarray(
        values,
        dtype=float
    )

    values=values[
        np.isfinite(values)
    ]

    if values.size < 2:
        return 0.0

    return float(
        np.percentile(values,90)
        -
        np.percentile(values,10)
    )


def groups(mask,gap):

    indexes=np.flatnonzero(mask)

    if indexes.size == 0:
        return []

    output=[]

    start=int(indexes[0])
    previous=int(indexes[0])

    for value in indexes[1:]:

        value=int(value)

        if (
            value
            -
            previous
            -
            1
            >
            gap
        ):
            output.append(
                (start,previous)
            )
            start=value

        previous=value

    output.append(
        (start,previous)
    )

    return output


def morphology(path):

    with np.load(
        path,
        allow_pickle=False
    ) as z:

        samples=np.asarray(
            z["samples"]
        )

        fs=float(
            np.asarray(
                z["sample_rate"]
            ).item()
        )


    if samples.size < 4096:
        raise RuntimeError(
            "za mało próbek"
        )


    NFFT=2048
    HOP=256

    window=hamming(
        NFFT,
        sym=True
    )

    sft=ShortTimeFFT(
        window,
        hop=HOP,
        fs=fs,
        mfft=NFFT,
        fft_mode="centered"
    )

    P=sft.spectrogram(
        samples
    )

    t=np.asarray(
        sft.t(
            len(samples)
        ),
        dtype=float
    )


    #
    # SDR pracuje ok. 2 kHz poniżej GRAVES.
    # 0 Hz poniżej oznacza częstotliwość GRAVES.
    #
    f=np.asarray(
        sft.f,
        dtype=float
    ) - 2000.0


    band=(
        (f >= -300.0)
        &
        (f <= 300.0)
    )

    P=np.asarray(
        P[band,:],
        dtype=float
    )

    f=f[band]


    db=10.0*np.log10(
        np.maximum(
            P,
            1e-24
        )
    )


    floor=np.percentile(
        db,
        35,
        axis=0
    )

    rel=db-floor[None,:]


    ridge_index=np.argmax(
        rel,
        axis=0
    )

    ridge_db=rel[
        ridge_index,
        np.arange(
            rel.shape[1]
        )
    ]

    ridge_hz=f[
        ridge_index
    ]


    active=ridge_db >= 8.0


    if len(t) >= 2:
        dt=float(
            np.median(
                np.diff(t)
            )
        )
    else:
        dt=HOP/fs


    dt=max(
        dt,
        0.001
    )


    event_groups=groups(
        active,
        max(
            1,
            round(
                0.18/dt
            )
        )
    )


    if not event_groups:

        return {
            "textbook_head_trail":False,
            "strict_features_passed":0,
            "strict_features_total":7
        }


    global_peak=int(
        np.argmax(
            ridge_db
        )
    )


    selected=None

    for group in event_groups:

        if (
            group[0]
            <= global_peak
            <= group[1]
        ):
            selected=group
            break


    if selected is None:

        selected=max(
            event_groups,
            key=lambda x:
                np.max(
                    ridge_db[
                        x[0]:x[1]+1
                    ]
                )
        )


    a,b=selected

    tt=t[a:b+1]
    ff=ridge_hz[a:b+1]
    dd=ridge_db[a:b+1]
    aa=active[a:b+1]


    duration=float(
        tt[-1]
        -
        tt[0]
        +
        dt
    )

    continuity=float(
        np.mean(aa)
    )

    span=robust_span(ff)

    peak=float(
        np.max(dd)
    )


    #
    # HEAD = pierwsze maks. 0.8 s / ~35% zdarzenia.
    #
    head_len=min(
        0.8,
        max(
            0.20,
            duration*0.35
        )
    )

    hm=tt <= (
        tt[0]
        +
        head_len
    )

    if np.count_nonzero(hm) < 3:

        hm=np.zeros(
            len(tt),
            dtype=bool
        )

        hm[
            :min(
                3,
                len(tt)
            )
        ]=True


    ht=tt[hm]
    hf=ff[hm]
    hd=dd[hm]


    head_duration=float(
        ht[-1]
        -
        ht[0]
        +
        dt
    )

    head_excursion=robust_span(
        hf
    )

    head_peak=float(
        np.max(hd)
    )


    if (
        len(ht) >= 3
        and
        np.ptp(ht) > 0
    ):

        head_drift=float(
            np.polyfit(
                ht-ht[0],
                hf,
                1
            )[0]
        )

    else:

        head_drift=0.0


    #
    # TRAIL = część po head echo.
    #
    tm=~hm

    trail_t=tt[tm]
    trail_f=ff[tm]
    trail_d=dd[tm]


    if len(trail_t) >= 2:

        trail_duration=float(
            trail_t[-1]
            -
            trail_t[0]
            +
            dt
        )

        trail_stability=robust_span(
            trail_f
        )

        trail_strength=float(
            np.median(
                trail_d
            )
        )

        trail_center=float(
            np.median(
                trail_f
            )
        )

    else:

        trail_duration=0.0
        trail_stability=999.0
        trail_strength=0.0
        trail_center=float("nan")


    n_end=max(
        1,
        min(
            len(hf),
            round(
                0.20/dt
            )
        )
    )

    head_end=float(
        np.median(
            hf[-n_end:]
        )
    )


    if np.isfinite(
        trail_center
    ):

        join=abs(
            trail_center
            -
            head_end
        )

    else:

        join=999.0


    broadband=float(
        np.mean(
            rel >= 8.0
        )
    )


    head_ok=bool(
        head_duration >= 0.15
        and
        head_peak >= 18.0
        and
        (
            abs(head_drift) >= 30.0
            or
            head_excursion >= 30.0
        )
    )


    trail_ok=bool(
        trail_duration >= 0.35
        and
        trail_strength >= 7.0
        and
        trail_stability <= 45.0
    )


    join_ok=bool(
        join <= 70.0
    )


    narrow_ok=bool(
        broadband <= 0.18
        and
        span <= 220.0
    )


    duration_ok=bool(
        0.35
        <= duration
        <= 6.5
    )


    peak_ok=bool(
        peak >= 20.0
    )


    continuity_ok=bool(
        continuity >= 0.72
    )


    flags={
        "head_echo":head_ok,
        "trail":trail_ok,
        "join":join_ok,
        "narrow":narrow_ok,
        "duration":duration_ok,
        "peak":peak_ok,
        "continuity":continuity_ok
    }


    passed=sum(
        int(v)
        for v
        in flags.values()
    )


    return {
        **flags,

        "textbook_head_trail":
            passed == 7,

        "strict_features_passed":
            passed,

        "strict_features_total":
            7,

        "event_duration_s":
            round(duration,3),

        "continuity_ratio":
            round(continuity,3),

        "event_span_hz":
            round(span,1),

        "head_duration_s":
            round(head_duration,3),

        "head_excursion_hz":
            round(head_excursion,1),

        "head_drift_hz_per_s":
            round(head_drift,1),

        "head_peak_db":
            round(head_peak,2),

        "trail_duration_s":
            round(trail_duration,3),

        "trail_stability_hz":
            round(trail_stability,1),

        "trail_strength_db":
            round(trail_strength,2),

        "head_trail_join_hz":
            round(join,1),

        "peak_over_floor_strict_db":
            round(peak,2),

        "broadband_occupancy_strict":
            round(broadband,4)
    }


def main():

    if len(sys.argv) != 2:

        emit({
            "ok":False,
            "error":"podaj plik SMP"
        })

        return 2


    source=Path(
        sys.argv[1]
    )


    try:

        base=run_core(
            source
        )

    except Exception as exc:

        emit({
            "ok":False,
            "error":str(exc)
        })

        return 1


    base[
        "heuristic_version"
    ]=VERSION


    if not base.get("ok"):

        emit(base)
        return 0


    kind=str(
        base.get(
            "kind",
            ""
        )
    ).lower()

    label=str(
        base.get(
            "label",
            ""
        )
    ).lower()


    meteor=(
        "meteor" in kind
        or
        "meteor" in label
    )


    old=int(
        round(
            float(
                base.get(
                    "confidence",
                    0
                )
            )
        )
    )

    old=max(
        0,
        min(
            100,
            old
        )
    )


    #
    # Inne klasy nigdy nie mają "meteor 100%".
    #
    if not meteor:

        base[
            "confidence"
        ]=min(
            old,
            99
        )

        base[
            "strict_100_rule"
        ]="non-meteor"

        emit(base)
        return 0


    try:

        shape=morphology(
            source
        )

    except Exception as exc:

        base[
            "confidence"
        ]=min(
            old,
            99
        )

        base[
            "strict_100_rule"
        ]="shape-analysis-error"

        base.setdefault(
            "metrics",
            {}
        )[
            "strict_shape_error"
        ]=str(exc)

        emit(base)
        return 0


    base.setdefault(
        "metrics",
        {}
    ).update(
        shape
    )


    passed=int(
        shape[
            "strict_features_passed"
        ]
    )


    #
    # 100% dopiero gdy:
    # - stara heurystyka już uważała go za bardzo mocnego
    # - nowy wzorzec ma komplet 7/7.
    #
    if (
        old >= 90
        and
        passed == 7
    ):

        score=100

        base[
            "strict_100_rule"
        ]="textbook-head-trail"

        base[
            "label"
        ]="kandydat meteor — head echo + trail"

        base[
            "explanation"
        ]=(
            "Pełny wzorzec 7/7: szybki head echo, "
            "stabilny trail, połączenie head→trail, "
            "wąskopasmowość, właściwy czas, moc i ciągłość. "
            "100% oznacza zgodność z naszą heurystyką."
        )


    elif passed == 6:

        score=max(
            min(old,99),
            98
        )

        base[
            "strict_100_rule"
        ]="6-of-7"


    elif passed == 5:

        score=max(
            min(old,97),
            95
        )

        base[
            "strict_100_rule"
        ]="5-of-7"


    elif passed == 4:

        score=min(
            max(old,92),
            94
        )

        base[
            "strict_100_rule"
        ]="4-of-7"


    else:

        score=min(
            old,
            94
        )

        base[
            "strict_100_rule"
        ]="below-4-of-7"


    base[
        "confidence"
    ]=int(score)

    emit(base)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
