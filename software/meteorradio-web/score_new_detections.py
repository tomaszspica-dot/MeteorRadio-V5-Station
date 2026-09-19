#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from pathlib import Path


RADAR=Path(
    "/home/pi/radar_data"
)

CACHE=Path(
    "/home/pi/meteorradio-web/cache"
)

INDEX=(
    CACHE
    /
    "v562_score_index.json"
)

MAX_PER_RUN=9223372036854775807  # UNLIMITED
MAX_TEMP=75.0

MAX_LOAD=3.50

MIN_AGE=30.0

HTTP_TIMEOUT=65


def log(*args):

    print(
        time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        *args,
        flush=True,
    )


def temperature():

    try:

        return (
            float(
                Path(
                    "/sys/class/thermal/"
                    "thermal_zone0/temp"
                )
                .read_text()
                .strip()
            )
            /
            1000.0
        )

    except Exception:

        return 99.0


def current_throttle():

    import subprocess

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

        value=int(
            p.stdout
            .strip()
            .split(
                "=",
                1
            )[1],
            16,
        )

        return (
            value
            &
            0xF
        )

    except Exception:

        return 0


def _mr_resource_check_once_v1():

    t=temperature()

    load=os.getloadavg()[0]

    throttle=current_throttle()


    log(
        "CHECK",
        f"temp={t:.1f}C",
        f"load={load:.2f}",
        f"throttle={hex(throttle)}",
    )


    if t >= MAX_TEMP:

        log(
            "PAUSE temperature"
        )

        return False


    if load >= MAX_LOAD:

        log(
            "PAUSE load"
        )

        return False


    if throttle:

        log(
            "PAUSE active-throttle"
        )

        return False


    return True


# ============================================================
# MR_RESOURCE_WAIT_RESUME_V1
# ============================================================

def safe(*args, **kwargs):
    """
    Kontrola zasobów z WAIT/RESUME.

    Pierwszy poprawny CHECK:
        działa natychmiast.

    Jeśli TEMP / LOAD / throttle zatrzyma scoring:
        worker NIE kończy kolejki,
        tylko czeka i ponawia CHECK.

    Po pauzie wymagamy dwóch kolejnych
    poprawnych kontroli, aby nie oscylować
    na granicy limitu.
    """

    import time as _mr_wait_time

    waiting = False
    stable_ok = 0

    while True:

        ok = _mr_resource_check_once_v1(
            *args,
            **kwargs
        )

        if ok:

            if not waiting:
                return True

            stable_ok += 1

            print(
                _mr_wait_time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "WAIT safe",
                f"stable={stable_ok}/2",
                flush=True
            )

            if stable_ok >= 2:

                print(
                    _mr_wait_time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "RESUME resources stable",
                    flush=True
                )

                return True

        else:

            if not waiting:

                print(
                    _mr_wait_time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "WAIT resources",
                    "recheck=15s",
                    flush=True
                )

            waiting = True
            stable_ok = 0

        _mr_wait_time.sleep(15)

# ============================================================
# END MR_RESOURCE_WAIT_RESUME_V1
# ============================================================



def read_index():

    try:

        d=json.loads(
            INDEX.read_text(
                encoding="utf-8"
            )
        )

        scores=d.get(
            "scores",
            {}
        )

        if isinstance(
            scores,
            dict
        ):

            return scores

    except Exception:

        pass


    return {}


def write_index(scores):

    CACHE.mkdir(
        parents=True,
        exist_ok=True,
    )


    payload={
        "ok":
            True,

        "version":
            "v562-score-index-1",

        "count":
            len(scores),

        "scores":
            scores,
    }


    fd,tmp=tempfile.mkstemp(
        prefix=".score-index-",
        suffix=".json",
        dir=str(CACHE),
    )


    try:

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


    finally:

        try:

            if os.path.exists(tmp):
                os.unlink(tmp)

        except Exception:

            pass



# MR_DELETE_NO_HEAD_AFTER_2_V1

NO_HEAD_INDEX=(
    CACHE
    /
    "v562_no_head_failures.json"
)

NO_HEAD_DELETE_AFTER=2


def read_no_head_failures():

    try:

        data=json.loads(
            NO_HEAD_INDEX.read_text(
                encoding="utf-8"
            )
        )

        failures=data.get(
            "failures",
            {}
        )

        if isinstance(
            failures,
            dict
        ):
            return failures

    except FileNotFoundError:
        pass

    except Exception as exc:

        log(
            "NO_HEAD_INDEX_READ_ERROR",
            repr(exc)
        )

    return {}


def write_no_head_failures(
    failures
):

    CACHE.mkdir(
        parents=True,
        exist_ok=True
    )

    payload={
        "version":
            "v562-no-head-failures-1",

        "delete_after":
            NO_HEAD_DELETE_AFTER,

        "updated":
            time.time(),

        "failures":
            failures,
    }

    fd,tmp=tempfile.mkstemp(
        prefix=".no-head-failures-",
        suffix=".json",
        dir=str(CACHE),
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                payload,
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

            f.flush()

            os.fsync(
                f.fileno()
            )

        os.replace(
            tmp,
            NO_HEAD_INDEX
        )

    finally:

        try:

            if os.path.exists(tmp):
                os.unlink(tmp)

        except Exception:
            pass


def no_head_attempts(
    name
):

    failures=read_no_head_failures()

    entry=failures.get(
        name,
        {}
    )

    if not isinstance(
        entry,
        dict
    ):
        return 0

    try:

        return int(
            entry.get(
                "attempts",
                0
            )
        )

    except Exception:
        return 0


def register_no_head_failure(
    src,
    exc
):

    failures=read_no_head_failures()

    old=failures.get(
        src.name,
        {}
    )

    if not isinstance(
        old,
        dict
    ):
        old={}

    try:

        previous=int(
            old.get(
                "attempts",
                0
            )
        )

    except Exception:
        previous=0

    attempts=previous+1

    now=time.time()

    entry={
        "attempts":
            attempts,

        "first_seen":
            old.get(
                "first_seen",
                now
            ),

        "last_seen":
            now,

        "last_error":
            str(exc)[-3000:],

        "deleted":
            False,
    }

    failures[
        src.name
    ]=entry

    write_no_head_failures(
        failures
    )

    return attempts


def mark_no_head_deleted(
    src
):

    failures=read_no_head_failures()

    entry=failures.get(
        src.name,
        {}
    )

    if not isinstance(
        entry,
        dict
    ):
        entry={}

    entry[
        "deleted"
    ]=True

    entry[
        "deleted_at"
    ]=time.time()

    failures[
        src.name
    ]=entry

    write_no_head_failures(
        failures
    )


def delete_no_head_file(
    src,
    attempts
):

    # Bezpiecznik:
    # kasujemy wyłącznie SMP_*.npz
    # i wyłącznie z RADAR.

    try:

        resolved=src.resolve()
        radar_resolved=RADAR.resolve()

    except Exception as exc:

        log(
            "DELETE_NO_HEAD_PATH_ERROR",
            src.name,
            repr(exc)
        )

        return False


    if resolved.parent != radar_resolved:

        log(
            "DELETE_NO_HEAD_REFUSED",
            str(resolved)
        )

        return False


    if (
        not src.name.startswith("SMP_")
        or
        src.suffix.lower() != ".npz"
    ):

        log(
            "DELETE_NO_HEAD_REFUSED",
            src.name
        )

        return False


    try:

        src.unlink()

        mark_no_head_deleted(
            src
        )

        log(
            "DELETE_NO_HEAD",
            src.name,
            f"attempt={attempts}"
        )

        return True

    except FileNotFoundError:

        mark_no_head_deleted(
            src
        )

        log(
            "DELETE_NO_HEAD_ALREADY_GONE",
            src.name
        )

        return True

    except Exception as exc:

        log(
            "DELETE_NO_HEAD_ERROR",
            src.name,
            repr(exc)
        )

        return False



def candidates(scores):

    now=time.time()


    files=sorted(
        RADAR.glob(
            "SMP_*.npz"
        ),
        key=lambda p:
            p.stat().st_mtime,
        reverse=True,
    )


    result=[]


    for src in files:

        if src.name in scores:
            continue


        try:

            age=(
                now
                -
                src.stat().st_mtime
            )

        except Exception:

            continue


        if age < MIN_AGE:
            continue


        result.append(
            src
        )


        if (
            len(result)
            >=
            MAX_PER_RUN
        ):

            break


    return result


def classify(src):

    query=urllib.parse.urlencode(
        {
            "file":
                src.name,

            "v":
                "562p1",
        }
    )


    url=(
        "http://127.0.0.1:8094/"
        "api/classification?"
        +
        query
    )


    request=urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "MeteorRadio-ScoreWorker/1"
        },
    )


    started=time.monotonic()


    with urllib.request.urlopen(
        request,
        timeout=HTTP_TIMEOUT,
    ) as response:

        raw=response.read()


    elapsed=(
        time.monotonic()
        -
        started
    )


    data=json.loads(
        raw.decode(
            "utf-8"
        )
    )


    if not data.get(
        "ok"
    ):

        raise RuntimeError(
            data.get(
                "error",
                "classification failed"
            )
        )


    score=int(
        data.get(
            "score"
        )
    )


    if not (
        1 <= score <= 7
    ):

        raise RuntimeError(
            f"bad score {score!r}"
        )


    return (
        score,
        elapsed,
    )




# MR_SCORE_TTL_1_7_V1
# MR_SCORE_TTL_1_7_CLEAN_V2
# Wyniki 1–7 są zapisywane do score-index.
# Kasowanie odbywa się wyłącznie przez politykę retencji
# lub ręczny czerwony X w 8096.








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


    if not safe():

        return 0


    scores=read_index()


    queue=candidates(
        scores
    )


    log(
        "INDEX",
        len(scores),
        "QUEUE",
        len(queue),
    )


    if not queue:

        log(
            "NO_MISSING"
        )

        return 0


    done=0


    # MR_DYNAMIC_QUEUE_V2
    seen_cycle=set()
    while queue:
        batch=queue
        queue=[]
        for src in batch:
            old_no_head=no_head_attempts(src.name)
            
            if old_no_head >= NO_HEAD_DELETE_AFTER:
                delete_no_head_file(
                    src,
                    old_no_head
                )
                continue
            
            seen_cycle.add(src.name)

            if not safe():
                break


            log(
                "SCORE",
                src.name
            )


            try:

                score,elapsed=classify(
                    src
                )



                scores[
                    src.name
                ]=score


                write_index(
                    scores
                )


                done+=1


                log(
                    "DONE",
                    src.name,
                    "score",
                    score,
                    f"{elapsed:.1f}s",
                    f"temp={temperature():.1f}C",
                )


            except Exception as e:

                if "Brak kandydata HEAD" in str(e):
                    attempts=register_no_head_failure(
                        src,
                        e
                    )
                
                    if attempts >= NO_HEAD_DELETE_AFTER:
                        delete_no_head_file(
                            src,
                            attempts
                        )
                    else:
                        log(
                            "RETRY_NO_HEAD",
                            src.name,
                            f"attempt={attempts}"
                        )
                
                log(
                    "ERROR",
                    src.name,
                    repr(e),
                )


            #
            # Nie zaczynamy kolejnego FFT od razu.
            #

            time.sleep(
                20
            )

        refreshed=[
            p
            for p in candidates(scores)
            if p.name not in seen_cycle
        ]

        if refreshed:
            log(
                'QUEUE_REFRESH',
                len(refreshed),
            )

        queue=refreshed


    log(
        "FINISH",
        f"done={done}",
        f"index={len(scores)}",
    )


    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
