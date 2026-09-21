#!/usr/bin/env python3

import csv
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from pathlib import Path


RADAR=Path(
    "/home/pi/radar_data"
)

WEB=Path(
    "/home/pi/meteorradio-web"
)

CACHE=WEB / "cache"

RENDERER=(
    WEB
    /
    "render_detection_v5.py"
)

INDEX=(
    CACHE
    /
    "v562_score_index.json"
)

HISTORY=Path(
    "/tmp/meteorradio_v562_history.tsv"
)

POINT_CACHE=(
    CACHE
    /
    "classification_v562_points"
)


MAX_TEMP_C=70.0

MAX_LOAD_1M=2.00

MIN_FILE_AGE_S=25.0

COOLDOWN_AFTER_RENDER_S=45.0

IDLE_SLEEP_S=20.0


def log(*args):

    print(
        time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        *args,
        flush=True,
    )


def temp_c():

    try:

        raw=Path(
            "/sys/class/thermal/"
            "thermal_zone0/temp"
        ).read_text().strip()

        return (
            float(raw)
            /
            1000.0
        )

    except Exception:

        return 99.0


def throttle_current():

    try:

        p=subprocess.run(
            [
                "vcgencmd",
                "get_throttled",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )

        text=p.stdout.strip()

        value=int(
            text.split(
                "=",
                1
            )[1],
            16,
        )

        #
        # Interesują nas wyłącznie
        # AKTYWNE bity 0..3.
        #
        # 0x80000 = historyczny bit,
        # więc nie blokuje pre-renderu.
        #

        return (
            value
            &
            0xF
        )

    except Exception:

        return 0


def heavy_helper_running():

    patterns=[
        "render_detection_v5.py",
        "classify_detection_v5.py",
        "classify_detection_v562_core.py",
        "classify_detection_v56_legacy.py",
    ]

    try:

        p=subprocess.run(
            [
                "ps",
                "-eo",
                "args=",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )

        lines=p.stdout.splitlines()

        for line in lines:

            if (
                "pre_render_cache.py"
                in line
            ):
                continue

            if any(
                pattern in line
                for pattern in patterns
            ):
                return True

    except Exception:

        pass

    return False


def safe_to_render():

    temperature=temp_c()

    load1=os.getloadavg()[0]

    throttled=throttle_current()


    if temperature >= MAX_TEMP_C:

        log(
            "PAUSE temp",
            f"{temperature:.1f}C",
        )

        return False


    if load1 >= MAX_LOAD_1M:

        log(
            "PAUSE load",
            f"{load1:.2f}",
        )

        return False


    if throttled != 0:

        log(
            "PAUSE active-throttle",
            hex(
                throttled
            ),
        )

        return False


    if heavy_helper_running():

        log(
            "PAUSE helper-active"
        )

        return False


    return True


def rebuild_score_index():

    # MR_PRERENDER_SCORE_INDEX_READONLY_V1
    #
    # Score-index jest własnością score_new_detections.py.
    # Pre-render może tworzyć PNG/cache, ale NIE może
    # rekonstruować ani nadpisywać indeksu ocen.
    #
    return

    scores={}


    if HISTORY.is_file():

        try:

            with HISTORY.open(
                encoding="utf-8"
            ) as f:

                for row in csv.DictReader(
                    f,
                    delimiter="\t",
                ):

                    name=row.get(
                        "file"
                    )

                    if not name:
                        continue

                    try:

                        raw=int(
                            row.get(
                                "new_passed",
                                ""
                            )
                        )

                    except Exception:

                        continue

                    scores[name]=max(
                        1,
                        min(
                            7,
                            raw
                        )
                    )

        except Exception:

            pass


    if POINT_CACHE.is_dir():

        for path in POINT_CACHE.glob(
            "v562p1_*.json"
        ):

            try:

                d=json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

                score=int(
                    d.get(
                        "score"
                    )
                )

                if not (
                    1 <= score <= 7
                ):
                    continue

                name=path.name[
                    len(
                        "v562p1_"
                    ):
                ]

                if name.endswith(
                    ".json"
                ):
                    name=name[:-5]

                scores[name]=score

            except Exception:

                pass


    for path in CACHE.glob(
        "SMP_*_v5_class.json"
    ):

        try:

            d=json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            score=int(
                d.get(
                    "score"
                )
            )

            if not (
                1 <= score <= 7
            ):
                continue

            name=path.name[
                :-len(
                    "_v5_class.json"
                )
            ]

            scores[
                name + ".npz"
            ]=score

        except Exception:

            pass


    payload={
        "ok": True,
        "version": "v562-score-index-1",
        "count": len(scores),
        "scores": scores,
    }


    try:

        CACHE.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd,tmp=tempfile.mkstemp(
            prefix=".score-index-",
            suffix=".json",
            dir=str(
                CACHE
            ),
        )

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                payload,
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            f.flush()

            os.fsync(
                f.fileno()
            )

        os.replace(
            tmp,
            INDEX
        )

    except Exception as e:

        log(
            "INDEX ERROR",
            repr(e)
        )


def cache_destination(src):

    return (
        CACHE
        /
        (
            src.stem
            +
            "_v52_mh1.png"
        )
    )



# ============================================================
# MR_BAD_NPZ_GUARD_V1
# ============================================================

def npz_is_valid(src):

    try:

        if (
            not src.is_file()
            or
            src.stat().st_size <= 0
        ):
            return False

        if not zipfile.is_zipfile(src):
            return False

        with zipfile.ZipFile(src, "r") as zf:

            names=set(zf.namelist())

            required={
                "samples.npy",
                "sample_rate.npy",
                "centre_freq.npy",
            }

            if not required.issubset(names):
                return False

            if zf.testzip() is not None:
                return False

        return True

    except Exception as exc:

        log(
            "NPZ_VALIDATE_ERROR",
            src.name,
            repr(exc),
        )

        return False


def needs_render(src):

    dst=cache_destination(
        src
    )


    if not dst.is_file():

        return True


    try:

        newest=max(
            src.stat().st_mtime,
            RENDERER.stat().st_mtime,
        )

        return (
            dst.stat().st_mtime
            <
            newest
        )

    except Exception:

        return True


def next_candidate():

    now=time.time()


    files=sorted(
        RADAR.glob(
            "SMP_*.npz"
        ),
        key=lambda p:
            p.stat().st_mtime,
        reverse=True,
    )


    for src in files:

        try:

            age=(
                now
                -
                src.stat().st_mtime
            )

        except Exception:

            continue


        if age < MIN_FILE_AGE_S:
            continue


        if needs_render(
            src
        ):

            # PRERENDER_SKIP_BAD_NPZ_V1
            if not npz_is_valid(src):

                log(
                    "SKIP_BAD_NPZ",
                    src.name,
                )

                continue

            return src


    return None


def render_via_web(src):

    query=urllib.parse.urlencode(
        {
            "file":
                src.name,

            "maxhold":
                "1",
        }
    )


    url=(
        "http://127.0.0.1:8094/"
        "detection-v5.png?"
        +
        query
    )


    req=urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "MeteorRadio-Prerender/1"
        },
    )


    with urllib.request.urlopen(
        req,
        timeout=95,
    ) as response:

        while True:

            chunk=response.read(
                65536
            )

            if not chunk:
                break


def main():

    try:

        os.nice(
            19
        )

    except Exception:

        pass


    log(
        "START"
    )


    time.sleep(
        15
    )


    while True:

        rebuild_score_index()


        if not safe_to_render():

            time.sleep(
                IDLE_SLEEP_S
            )

            continue


        src=next_candidate()


        if src is None:

            time.sleep(
                30
            )

            continue


        before=temp_c()

        load1=os.getloadavg()[0]


        log(
            "RENDER",
            src.name,
            "temp",
            f"{before:.1f}",
            "load",
            f"{load1:.2f}",
        )


        started=time.monotonic()


        try:

            render_via_web(
                src
            )

            elapsed=(
                time.monotonic()
                -
                started
            )

            log(
                "DONE",
                src.name,
                f"{elapsed:.1f}s",
                "temp",
                f"{temp_c():.1f}",
            )


        except Exception as e:

            log(
                "ERROR",
                src.name,
                repr(e),
            )


        time.sleep(
            COOLDOWN_AFTER_RENDER_S
        )


if __name__ == "__main__":

    main()
