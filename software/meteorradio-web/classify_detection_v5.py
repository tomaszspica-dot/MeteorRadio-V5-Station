#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile

from pathlib import Path


VERSION = "v5.6.2-anchor-head-trail-points-v1"

LEGACY = Path(
    "/home/pi/meteorradio-web/"
    "classify_detection_v56_legacy.py"
)

CORE = Path(
    "/home/pi/meteorradio-web/"
    "classify_detection_v562_core.py"
)

CACHE_DIR = Path(
    "/home/pi/meteorradio-web/"
    "cache/classification_v562_points"
)


FEATURE_ORDER = [
    "head_echo",
    "trail",
    "join",
    "narrow",
    "duration",
    "peak",
    "continuity",
]


FEATURE_LABELS = {

    "head_echo":
        "HEAD",

    "trail":
        "TRAIL",

    "join":
        "JOIN",

    "narrow":
        "NARROW",

    "duration":
        "DURATION",

    "peak":
        "PEAK",

    "continuity":
        "CONTINUITY",
}


def output(data):

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def fail(message):

    output(
        {
            "ok":
                False,

            "error":
                str(
                    message
                ),

            "heuristic_version":
                VERSION,
        }
    )

    raise SystemExit(0)


def run_json(
    script,
    source,
    timeout_s,
):

    try:

        p = subprocess.run(
            [
                sys.executable,
                str(script),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            f"timeout: {script.name}"
        )


    if p.returncode != 0:

        raise RuntimeError(
            (
                p.stderr.strip()
                or
                f"{script.name}: rc={p.returncode}"
            )
        )


    try:

        return json.loads(
            p.stdout
        )

    except Exception as e:

        raise RuntimeError(
            f"{script.name}: JSON {e!r}"
        )


if len(sys.argv) != 2:

    fail(
        "usage: classify_detection_v5.py FILE.npz"
    )


SRC = Path(
    sys.argv[1]
)


if not SRC.is_file():

    fail(
        "brak pliku SMP"
    )


if not LEGACY.is_file():

    fail(
        "brak legacy V5.6"
    )


if not CORE.is_file():

    fail(
        "brak core V5.6.2"
    )


#
# Klasyfikator jest procesem pomocniczym,
# więc obniżamy mu priorytet względem
# pracującego MeteorRadio.
#

try:

    os.nice(
        10
    )

except Exception:

    pass


CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


cache_path = (
    CACHE_DIR
    /
    (
        "v562p1_"
        +
        SRC.name
        +
        ".json"
    )
)


#
# SMP jest plikiem niezmiennym.
# Gotowej klasyfikacji nie liczymy drugi raz.
#

if cache_path.is_file():

    try:

        cached = json.loads(
            cache_path.read_text(
                encoding="utf-8"
            )
        )


        if (
            cached.get(
                "heuristic_version"
            )
            ==
            VERSION
        ):

            output(
                cached
            )

            raise SystemExit(0)


    except SystemExit:

        raise

    except Exception:

        pass


try:

    #
    # V5.6.2:
    # HEAD / TRAIL / JOIN / PEAK / CONTINUITY
    # + czas + chwilowa szerokość
    #

    new = run_json(
        CORE,
        SRC,
        25,
    )


    #
    # Stary V5.6:
    # zachowujemy DOKŁADNIE tę samą
    # metrykę broadband co w audycie historii.
    #

    old = run_json(
        LEGACY,
        SRC,
        35,
    )


except Exception as e:

    fail(
        repr(
            e
        )
    )


flags = dict(
    new.get(
        "known_flags",
        {}
    )
)


event = new.get(
    "event",
    {}
)

head = new.get(
    "head",
    {}
)

trail = new.get(
    "trail",
    {}
)

join = new.get(
    "join",
    {}
)

anchor = new.get(
    "anchor",
    {}
)


old_metrics = old.get(
    "metrics",
    {}
)


#
# Dokładnie taka sama kolejność źródeł,
# jak w naszym pełnym audycie 309 rekordów:
#
# 1. broadband_occupancy_strict
# 2. fallback broadband_occupancy
#

broadband_source = (
    "broadband_occupancy_strict"
)


broadband = old_metrics.get(
    "broadband_occupancy_strict"
)


if broadband is None:

    broadband_source = (
        "broadband_occupancy"
    )

    broadband = old_metrics.get(
        "broadband_occupancy"
    )


try:

    broadband = float(
        broadband
    )

except Exception:

    broadband = 999.0


try:

    duration = float(
        event.get(
            "duration_s",
            0.0
        )
    )

except Exception:

    duration = 0.0


try:

    width = float(
        event.get(
            "p90_instant_width_hz",
            9999.0
        )
    )

except Exception:

    width = 9999.0


# ============================================================
# 7 CECH
# ============================================================

#
# Nie zmieniamy progów.
#
# NARROW:
# broadband <= 0.18
# chwilowa szerokość <= 220 Hz
#

flags["narrow"] = bool(
    broadband <= 0.18
    and
    width <= 220.0
)


#
# DURATION:
# 0.35 ... 6.5 s
#

flags["duration"] = bool(
    0.35
    <=
    duration
    <=
    6.5
)


for name in FEATURE_ORDER:

    flags.setdefault(
        name,
        False
    )


raw_passed = sum(
    bool(
        flags[name]
    )
    for name in FEATURE_ORDER
)


#
# Interfejs ma skalę 1–7.
#
# raw_passed pozostaje dostępne osobno,
# więc niczego nie ukrywamy.
#

score = max(
    1,
    min(
        7,
        raw_passed
    )
)


features = {

    name: {

        "label":
            FEATURE_LABELS[
                name
            ],

        "passed":
            bool(
                flags[
                    name
                ]
            ),
    }

    for name in FEATURE_ORDER
}


result = {

    "ok":
        True,


    "kind":
        (
            "meteor"
            if raw_passed == 7
            else "uncertain"
        ),


    "label":
        f"ocena {score}/7",


    "score":
        score,

    "score_total":
        7,


    "features_passed":
        raw_passed,

    "features_total":
        7,


    "features":
        features,


    #
    # Pole pozostaje tylko po to,
    # aby starsze sortowanie panelu
    # nadal działało.
    #
    # To NIE jest procent.
    #

    "confidence":
        score,

    "confidence_semantics":
        "points_1_to_7_not_percent",


    "explanation":
        (
            f"Ocena punktowa {score}/7. "
            f"Spełnione cechy: {raw_passed}/7."
        ),


    "metrics": {

        "head_echo":
            bool(
                flags["head_echo"]
            ),

        "trail":
            bool(
                flags["trail"]
            ),

        "join":
            bool(
                flags["join"]
            ),

        "narrow":
            bool(
                flags["narrow"]
            ),

        "duration":
            bool(
                flags["duration"]
            ),

        "peak":
            bool(
                flags["peak"]
            ),

        "continuity":
            bool(
                flags["continuity"]
            ),


        "strict_features_passed":
            raw_passed,

        "strict_features_total":
            7,


        "score_points":
            score,

        "score_total":
            7,


        "textbook_head_trail":
            bool(
                raw_passed == 7
            ),


        "event_duration_s":
            round(
                duration,
                3
            ),

        "instant_width_p90_hz":
            round(
                width,
                1
            ),


        "broadband_occupancy":
            round(
                broadband,
                4
            ),

        "broadband_source":
            broadband_source,


        "anchor_peak_db":
            anchor.get(
                "peak_db"
            ),

        "anchor_frequency_hz":
            anchor.get(
                "freq_hz"
            ),


        "head_duration_s":
            head.get(
                "duration_s"
            ),

        "head_peak_db":
            head.get(
                "peak_db"
            ),

        "head_r2":
            head.get(
                "r2"
            ),

        "head_occupancy":
            head.get(
                "occupancy"
            ),

        "head_excursion_hz":
            head.get(
                "excursion_hz"
            ),

        "head_drift_hz_per_s":
            head.get(
                "drift_hz_per_s"
            ),


        "trail_duration_s":
            trail.get(
                "duration_s"
            ),

        "trail_stability_hz":
            trail.get(
                "stability_hz"
            ),

        "trail_strength_db":
            trail.get(
                "strength_db"
            ),

        "trail_continuity":
            trail.get(
                "continuity_ratio"
            ),


        "head_trail_join_hz":
            join.get(
                "hz"
            ),
    },


    "legacy_version":
        old.get(
            "heuristic_version"
        ),


    "heuristic_version":
        VERSION,
}


#
# Cache zapisujemy atomowo.
#

try:

    fd, tmp_name = tempfile.mkstemp(
        prefix=".v562-",
        suffix=".json",
        dir=str(
            CACHE_DIR
        ),
    )

    with os.fdopen(
        fd,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        f.flush()

        os.fsync(
            f.fileno()
        )


    os.replace(
        tmp_name,
        cache_path
    )


except Exception:

    pass


output(
    result
)
