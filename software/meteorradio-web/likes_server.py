#!/usr/bin/env python3

# MR_LIKES_SCORE_1_7_V2

import fcntl
import html
import json
import mimetypes
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

from pathlib import Path


BASE=Path("/home/pi/meteorradio-web")
CACHE=BASE/"cache"
RADAR=Path("/home/pi/radar_data")

INDEX=CACHE/"v562_score_index.json"
LIKES=CACHE/"v562_likes.json"
STATE=CACHE/"v562_retention_state.json"
LOCK=CACHE/"v562_likes.lock"

LEDGER=CACHE/"v562_retention_deleted.jsonl"

PORT=8096


POLICY_DAYS={
    1:1,
    2:2,
    3:3,
    4:4,
    5:5,
    6:6,
    7:7,
}


_IMAGE_MAP={}
_IMAGE_MAP_TIME=0.0
_IMAGE_MAP_LOCK=threading.Lock()


# MR_8096_AUDIO_V3
AUDIO_CACHE=CACHE/"audio"
AUDIO_RENDER=BASE/"render_audio_v1.py"
AUDIO_ORIGINAL_RENDER=BASE/"render_audio_original_v1.py"
AUDIO_ORIGINAL_CACHE=CACHE/"audio-original"
AUDIO_PY=Path("/home/pi/vMeteorRadio/bin/python")

_AUDIO_BUILD_LOCK=threading.Lock()
_AUDIO_ORIGINAL_BUILD_LOCK=threading.Lock()

# MR_8096_AUDIO_DOWNLOAD_V1



def load(path,default):

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except FileNotFoundError:

        return default


def atomic_json(path,data):

    tmp=path.with_name(
        path.name
        +
        ".tmp-"
        +
        str(os.getpid())
    )

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True
        )
        +
        "\n",
        encoding="utf-8"
    )

    os.replace(
        tmp,
        path
    )


def score_value(raw):

    try:

        if isinstance(
            raw,
            dict
        ):

            raw=raw.get(
                "score",
                raw.get(
                    "value",
                    raw.get("rating")
                )
            )

        return int(raw)

    except Exception:

        return None


def safe_name(name):

    name=str(
        name or ""
    ).strip()

    if (
        not name.startswith("SMP_")
        or
        not name.endswith(".npz")
        or
        Path(name).name != name
        or
        ".." in name
    ):

        raise ValueError(
            "Nieprawidłowa nazwa SMP"
        )

    return name


def scoring_active():

    try:

        r=subprocess.run(
            [
                "/usr/bin/systemctl",
                "is-active",
                "--quiet",
                "meteorradio-score-new.service",
            ],
            check=False,
            timeout=4
        )

        return (
            r.returncode == 0
        )

    except Exception:

        return True


def snapshot():

    now=time.time()

    index_data=load(
        INDEX,
        {"scores":{}}
    )

    likes_data=load(
        LIKES,
        {"likes":{}}
    )

    state_data=load(
        STATE,
        {"qualified_at":{}}
    )


    scores=(
        index_data.get(
            "scores",
            index_data
        )
        if isinstance(
            index_data,
            dict
        )
        else {}
    )

    likes=likes_data.get(
        "likes",
        {}
    )

    qualified=state_data.get(
        "qualified_at",
        {}
    )


    if not isinstance(
        scores,
        dict
    ):
        scores={}

    if not isinstance(
        likes,
        dict
    ):
        likes={}

    if not isinstance(
        qualified,
        dict
    ):
        qualified={}


    items=[]

    counts={
        str(n):0
        for n in range(1,8)
    }


    for name,raw in scores.items():

        score=score_value(
            raw
        )

        if score not in POLICY_DAYS:
            continue

        p=RADAR/name

        if not p.is_file():
            continue


        liked=(
            name in likes
        )


        try:

            q=float(
                qualified.get(
                    name,
                    now
                )
            )

        except Exception:

            q=now


        ttl_seconds=(
            POLICY_DAYS[
                score
            ]
            *
            86400
        )

        expires=(
            q
            +
            ttl_seconds
        )

        remaining=max(
            0,
            expires-now
        )


        items.append(
            {
                "file":name,
                "score":score,
                "liked":liked,
                "qualified_at":q,
                "ttl_days":
                    POLICY_DAYS[
                        score
                    ],
                "expires_at":expires,
                "remaining_seconds":
                    remaining,
                "bytes":
                    p.stat().st_size,
            }
        )

        counts[
            str(score)
        ]+=1


    #
    # Nazwa SMP zawiera YYYYMMDD_HHMMSS,
    # więc reverse po nazwie daje nam najnowsze.
    #
    items.sort(
        key=lambda x:
            x["file"],
        reverse=True
    )


    return {
        "ok":True,
        "time":now,
        "items":items,
        "total":len(items),
        "liked":sum(
            1
            for x in items
            if x["liked"]
        ),
        "counts":counts,
        "policy_days":{
            str(k):v
            for k,v
            in POLICY_DAYS.items()
        },
    }


def toggle_like(name):

    name=safe_name(
        name
    )

    LOCK.touch(
        exist_ok=True
    )


    with LOCK.open("a+") as lock_f:

        fcntl.flock(
            lock_f.fileno(),
            fcntl.LOCK_EX
        )

        try:

            index_data=load(
                INDEX,
                {"scores":{}}
            )

            likes_data=load(
                LIKES,
                {
                    "version":1,
                    "likes":{}
                }
            )


            scores=(
                index_data.get(
                    "scores",
                    index_data
                )
                if isinstance(
                    index_data,
                    dict
                )
                else {}
            )

            if not isinstance(
                scores,
                dict
            ):
                scores={}


            if name not in scores:

                raise ValueError(
                    "Detekcji nie ma w score-index"
                )


            score=score_value(
                scores[
                    name
                ]
            )

            if score not in POLICY_DAYS:

                raise ValueError(
                    "Dozwolone są oceny 1–7"
                )


            if not (
                RADAR/name
            ).is_file():

                raise ValueError(
                    "Plik SMP nie istnieje"
                )


            likes=likes_data.get(
                "likes",
                {}
            )

            if not isinstance(
                likes,
                dict
            ):
                likes={}


            if name in likes:

                likes.pop(
                    name,
                    None
                )

                liked=False

            else:

                likes[
                    name
                ]={
                    "liked_at":
                        time.time(),
                    "score":
                        score,
                }

                liked=True


            likes_data["version"]=1
            likes_data["updated"]=time.time()
            likes_data["likes"]=likes


            atomic_json(
                LIKES,
                likes_data
            )


            return {
                "ok":True,
                "file":name,
                "score":score,
                "liked":liked,
            }


        finally:

            fcntl.flock(
                lock_f.fileno(),
                fcntl.LOCK_UN
            )


def delete_cache(name):

    stem=Path(name).stem
    count=0


    for p in list(
        CACHE.rglob("*")
    ):

        try:

            if (
                p.is_file()
                and
                stem in p.name
            ):

                p.unlink()
                count+=1

        except FileNotFoundError:
            pass


    return count


def append_ledger(record):

    with LEDGER.open(
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True
            )
            +
            "\n"
        )

        f.flush()
        os.fsync(
            f.fileno()
        )


def manual_delete(name):

    name=safe_name(
        name
    )


    if scoring_active():

        raise RuntimeError(
            "Scoring jest teraz aktywny. "
            "Spróbuj ponownie po zakończeniu cyklu."
        )


    LOCK.touch(
        exist_ok=True
    )


    with LOCK.open("a+") as lock_f:

        fcntl.flock(
            lock_f.fileno(),
            fcntl.LOCK_EX
        )

        try:

            index_data=load(
                INDEX,
                {"scores":{}}
            )

            likes_data=load(
                LIKES,
                {
                    "version":1,
                    "likes":{}
                }
            )

            state_data=load(
                STATE,
                {
                    "version":2,
                    "qualified_at":{}
                }
            )


            scores=(
                index_data.get(
                    "scores",
                    index_data
                )
                if isinstance(
                    index_data,
                    dict
                )
                else {}
            )


            if not isinstance(
                scores,
                dict
            ):
                scores={}


            if name not in scores:

                raise ValueError(
                    "Detekcji nie ma już w score-index"
                )


            score=score_value(
                scores[
                    name
                ]
            )


            if score not in POLICY_DAYS:

                raise ValueError(
                    "Ręczne DELETE dozwolone dla score 1–7"
                )


            src=RADAR/name

            if not src.is_file():

                raise ValueError(
                    "Plik SMP już nie istnieje"
                )


            size=src.stat().st_size
            now=time.time()


            likes=likes_data.get(
                "likes",
                {}
            )

            if not isinstance(
                likes,
                dict
            ):
                likes={}


            qualified=state_data.get(
                "qualified_at",
                {}
            )

            if not isinstance(
                qualified,
                dict
            ):
                qualified={}


            was_liked=(
                name
                in
                likes
            )


            pending=src.with_name(
                src.name
                +
                ".manual-delete-pending"
            )


            os.replace(
                src,
                pending
            )


            try:

                scores.pop(
                    name,
                    None
                )

                likes.pop(
                    name,
                    None
                )

                qualified.pop(
                    name,
                    None
                )


                if (
                    isinstance(
                        index_data,
                        dict
                    )
                    and
                    "scores"
                    in index_data
                ):

                    index_data[
                        "scores"
                    ]=scores

                else:

                    index_data=scores


                likes_data[
                    "likes"
                ]=likes

                likes_data[
                    "updated"
                ]=now


                state_data[
                    "qualified_at"
                ]=qualified

                state_data[
                    "updated"
                ]=now


                atomic_json(
                    INDEX,
                    index_data
                )

                atomic_json(
                    LIKES,
                    likes_data
                )

                atomic_json(
                    STATE,
                    state_data
                )


            except Exception:

                if (
                    pending.exists()
                    and
                    not src.exists()
                ):

                    os.replace(
                        pending,
                        src
                    )

                raise


            cache_count=delete_cache(
                name
            )


            if pending.exists():
                pending.unlink()


            append_ledger(
                {
                    "time":now,
                    "file":name,
                    "score":score,
                    "bytes":size,
                    "cache_deleted":
                        cache_count,
                    "npz_existed":True,
                    "liked":
                        was_liked,
                    "source":
                        "manual_8096",
                }
            )


            print(
                "MANUAL_DELETE",
                name,
                "score=",
                score,
                "liked=",
                was_liked,
                "bytes=",
                size,
                "cache=",
                cache_count,
                flush=True
            )


            return {
                "ok":True,
                "file":name,
                "score":score,
                "liked":was_liked,
                "bytes":size,
                "cache_deleted":
                    cache_count,
            }


        finally:

            fcntl.flock(
                lock_f.fileno(),
                fcntl.LOCK_UN
            )


# MR_8096_AUDIO_V3

def prune_audio_cache():

    try:

        AUDIO_CACHE.mkdir(
            parents=True,
            exist_ok=True,
        )

        files=[]

        for p in AUDIO_CACHE.glob(
            "*.wav"
        ):

            try:

                if p.is_file():
                    files.append(p)

            except OSError:
                pass


        files.sort(
            key=lambda p:
                p.stat().st_mtime,
            reverse=True,
        )


        now=time.time()


        for i,p in enumerate(files):

            try:

                age=(
                    now
                    -
                    p.stat().st_mtime
                )

                if (
                    i >= 128
                    or
                    age > 7*86400
                ):
                    p.unlink()

            except FileNotFoundError:
                pass

            except OSError:
                pass


    except Exception as e:

        print(
            "AUDIO_CACHE_PRUNE_ERROR",
            repr(e),
            flush=True,
        )



def cached_audio(name):

    name=safe_name(
        name
    )

    src=RADAR/name


    if not src.is_file():

        raise FileNotFoundError(
            name
        )


    AUDIO_CACHE.mkdir(
        parents=True,
        exist_ok=True,
    )


    dst=AUDIO_CACHE / (
        Path(name).stem
        +
        "_usb.wav"
    )


    def current():

        try:

            return (
                dst.is_file()
                and
                dst.stat().st_size > 44
                and
                dst.stat().st_mtime
                >=
                src.stat().st_mtime
            )

        except OSError:

            return False


    #
    # Cache hit = zero DSP.
    #
    if current():

        return dst


    #
    # Maksymalnie jedna generacja naraz.
    #
    with _AUDIO_BUILD_LOCK:

        if current():

            return dst


        if not AUDIO_RENDER.is_file():

            raise RuntimeError(
                "Brak render_audio_v1.py"
            )


        if not AUDIO_PY.is_file():

            raise RuntimeError(
                "Brak Python vMeteorRadio"
            )


        cmd=[
            "/usr/bin/nice",
            "-n",
            "10",
            str(AUDIO_PY),
            str(AUDIO_RENDER),
            str(src),
            str(dst),
        ]


        started=time.monotonic()


        r=subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )


        elapsed=(
            time.monotonic()
            -
            started
        )


        if r.returncode != 0:

            raise RuntimeError(
                "Audio render failed: "
                +
                (
                    r.stdout
                    or
                    ""
                ).strip()
            )


        if not current():

            raise RuntimeError(
                "Nie powstał poprawny WAV"
            )


        print(
            "AUDIO_RENDER",
            name,
            f"{elapsed:.3f}s",
            (
                r.stdout
                or
                ""
            ).strip(),
            flush=True,
        )


        prune_audio_cache()


        return dst



# MR_8096_AUDIO_DOWNLOAD_V1

def cached_original_audio(name):

    name=safe_name(
        name
    )


    src=RADAR/name


    if not src.is_file():

        raise FileNotFoundError(
            name
        )


    AUDIO_ORIGINAL_CACHE.mkdir(
        parents=True,
        exist_ok=True,
    )


    dst=AUDIO_ORIGINAL_CACHE / (
        Path(name).stem
        +
        "_original_usb.wav"
    )


    def current():

        try:

            return (
                dst.is_file()
                and
                dst.stat().st_size > 44
                and
                dst.stat().st_mtime
                >=
                src.stat().st_mtime
            )

        except OSError:

            return False


    if current():

        return dst


    with _AUDIO_ORIGINAL_BUILD_LOCK:

        if current():

            return dst


        if not AUDIO_ORIGINAL_RENDER.is_file():

            raise RuntimeError(
                "Brak render_audio_original_v1.py"
            )


        cmd=[
            "/usr/bin/nice",
            "-n",
            "10",
            str(AUDIO_PY),
            str(AUDIO_ORIGINAL_RENDER),
            str(src),
            str(dst),
        ]


        r=subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )


        if r.returncode != 0:

            raise RuntimeError(
                "Original audio render failed: "
                +
                (
                    r.stdout
                    or
                    ""
                ).strip()
            )


        if not current():

            raise RuntimeError(
                "Nie powstał poprawny oryginalny WAV"
            )


        print(
            "AUDIO_ORIGINAL_RENDER",
            name,
            (
                r.stdout
                or
                ""
            ).strip(),
            flush=True,
        )


        #
        # Osobny mały cache.
        #
        try:

            files=sorted(
                [
                    p
                    for p
                    in AUDIO_ORIGINAL_CACHE.glob(
                        "*.wav"
                    )
                    if p.is_file()
                ],
                key=lambda p:
                    p.stat().st_mtime,
                reverse=True,
            )


            for old in files[128:]:

                try:
                    old.unlink()
                except OSError:
                    pass

        except Exception:
            pass


        return dst



def rebuild_image_map():

    global _IMAGE_MAP
    global _IMAGE_MAP_TIME

    now=time.time()


    with _IMAGE_MAP_LOCK:

        if (
            now
            -
            _IMAGE_MAP_TIME
            <
            30
        ):
            return


        m={}


        for p in CACHE.rglob("*"):

            try:

                if (
                    not p.is_file()
                    or
                    p.suffix.lower()
                    not in (
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".webp",
                    )
                ):
                    continue


                name=p.name


                if "SMP_" not in name:
                    continue


                start=name.find(
                    "SMP_"
                )


                for suffix in (
                    ".npz",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                ):

                    end=name.find(
                        suffix,
                        start
                    )

                    if end > start:

                        stem=name[
                            start:end
                        ]

                        old=m.get(
                            stem
                        )

                        #
                        # Wybierz największy obraz,
                        # zwykle właściwy pełny render.
                        #
                        if (
                            old is None
                            or
                            p.stat().st_size
                            >
                            old.stat().st_size
                        ):

                            m[
                                stem
                            ]=p

                        break


            except Exception:
                pass


        _IMAGE_MAP=m
        _IMAGE_MAP_TIME=now


def cached_image(name):

    """
    MR_8096_DIRECT_CACHE_V1

    Panel 8096 nie wymaga świeżego renderu.
    Jeśli istnieje poprawny PNG dla SMP,
    pokazujemy go NATYCHMIAST.

    Pre-render może później podmienić
    stary PNG na nową wersję w tle.
    """

    try:

        safe=Path(
            str(name)
        ).name

        stem=Path(
            safe
        ).stem

        candidates=[
            CACHE / f"{stem}_v52_mh1.png",
            CACHE / f"{stem}_v52_mh0.png",
            CACHE / f"{stem}_v5_mh1.png",
            CACHE / f"{stem}_v5_mh0.png",
        ]

        for candidate in candidates:

            try:

                if (
                    candidate.is_file()
                    and
                    candidate.stat().st_size
                    >=
                    1000
                ):

                    with candidate.open("rb") as f:
                        if (
                            f.read(8)
                            ==
                            b"\x89PNG\r\n\x1a\n"
                        ):
                            return candidate

            except Exception:
                pass


        # Starsze / nietypowe nazwy cache.
        try:

            for candidate in CACHE.glob(
                stem + "*.png"
            ):

                try:

                    if (
                        candidate.is_file()
                        and
                        candidate.stat().st_size
                        >=
                        1000
                    ):

                        with candidate.open("rb") as f:
                            if (
                                f.read(8)
                                ==
                                b"\x89PNG\r\n\x1a\n"
                            ):
                                return candidate

                except Exception:
                    continue

        except Exception:
            pass


        # Ostatnia zgodność ze starą mapą.
        try:

            rebuild_image_map()

            return (
                _IMAGE_MAP.get(safe)
                or
                _IMAGE_MAP.get(stem)
                or
                _IMAGE_MAP.get(name)
            )

        except Exception:

            return None

    except Exception:

        return None


HTML=r'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MeteorRadio — Ulubione</title>

<style>

*{
    box-sizing:border-box;
}

body{
    margin:0;
    background:#101010;
    color:#f1f1f1;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

header{
    position:sticky;
    top:0;
    z-index:20;
    background:#171717;
    border-bottom:1px solid #333;
    padding:13px;
}

h1{
    margin:0 0 9px 0;
    font-size:17px;
}

.toolbar{
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:7px;
}

.filter{
    border:1px solid #555;
    border-radius:6px;
    background:#292929;
    color:#fff;
    min-width:31px;
    height:30px;
    padding:0 9px;
    cursor:pointer;
}

.filter.active{
    background:#555;
    border-color:#aaa;
}

#summary{
    color:#aaa;
    font-size:12px;
    margin-left:4px;
}

.grid{
    display:grid;
    grid-template-columns:
        repeat(
            5,
            minmax(220px,1fr)
        );
    gap:10px;
    padding:10px;
}

.card{
    overflow:hidden;
    border:1px solid #3a3a3a;
    border-radius:8px;
    background:#1b1b1b;
}

.card.liked{
    border-color:#ff3b30;
}

.preview{
    width:100%;
    aspect-ratio:1.72/1;
    display:block;
    object-fit:cover;
    background:#111;
}

.cardbody{
    padding:9px 10px 8px 10px;
}

.title-row{
    display:flex;
    align-items:center;
    gap:8px;
}

.score{
    font-weight:700;
    font-size:16px;
    flex:1 1 auto;
}

/* MR_8096_AUDIO_V3 */

/* MR_8096_IQ_DOWNLOAD_V1 */

.iq-download{
    border:1px solid #507891;
    border-radius:4px;
    background:#132733;
    color:#9fe0ff;
    font-family:monospace;
    font-size:11px;
    font-weight:800;
    line-height:1;
    padding:4px 5px;
    min-width:28px;
    cursor:pointer;
    text-decoration:none;
    display:inline-flex;
    align-items:center;
    justify-content:center;
}

.iq-download:hover{
    background:#1e3b4d;
    color:#ffffff;
}


/* MR_8096_AUDIO_DOWNLOAD_V1 */

.audio-download{
    border:0;
    background:transparent;
    color:#8fd3ff;
    font-size:22px;
    line-height:1;
    padding:0 3px;
    min-width:28px;
    cursor:pointer;
    text-decoration:none;
    display:inline-flex;
    align-items:center;
    justify-content:center;
}

.audio-download:hover{
    color:#ffffff;
    transform:translateY(1px);
}

.audio-play{
    border:0;
    background:transparent;
    color:#f1f1f1;
    font-size:22px;
    line-height:1;
    padding:0 3px;
    min-width:28px;
    cursor:pointer;
}

.audio-play:hover{
    transform:scale(1.08);
}

.audio-play.playing{
    color:#67d5ff;
}

.audio-play:disabled{
    opacity:.55;
    cursor:wait;
}

.delete{
    border:0;
    background:transparent;
    color:#ff3b30;
    font-size:27px;
    line-height:1;
    padding:0 7px;
    cursor:pointer;
}

.heart{
    border:0;
    background:transparent;
    font-size:25px;
    line-height:1;
    padding:0;
    cursor:pointer;
}

.heart.on{
    color:#ff3b30;
}

.heart.off{
    color:#fff;
}

.filename{
    margin-top:7px;
    color:#999;
    font-size:10px;
    overflow-wrap:anywhere;
}

.retention{
    margin-top:7px;
    font-size:11px;
    color:#bbb;
}

.forever{
    color:#ddd;
}

.empty{
    padding:40px;
    color:#aaa;
}



/* MR_8096_BULK_DELETE_UNLIKED_V2 */

.bulk-delete-unliked{
    appearance:none;
    border:1px solid #d84848;
    border-radius:5px;
    background:#351818;
    color:#ffb1b1;
    padding:5px 10px;
    font-size:12px;
    font-weight:700;
    cursor:pointer;
    white-space:nowrap;
}

.bulk-delete-unliked:hover{
    background:#4a1d1d;
    border-color:#ff5c5c;
    color:#ffffff;
}

.bulk-delete-unliked:disabled{
    opacity:.55;
    cursor:wait;
}

@media(max-width:1200px){
    .grid{
        grid-template-columns:
            repeat(
                3,
                minmax(220px,1fr)
            );
    }
}

@media(max-width:750px){
    .grid{
        grid-template-columns:1fr;
    }
}


/* MR_REAL_TOP_NAV_8096_V1 */

.mr-title-row{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
}

.mr-nav-actions{
    display:flex;
    align-items:center;
    gap:8px;
    margin-left:auto;
}

a.mr-nav-btn,
button.mr-nav-btn{
    border:1px solid var(--line);
    background:#182b3a;
    color:#fff;
    border-radius:7px;
    padding:8px 12px;
    text-decoration:none;
    cursor:pointer;
    font-weight:700;
    font-size:12px;
    font-family:inherit;
    line-height:1.2;
    white-space:nowrap;
}

@media(max-width:750px){

    .mr-title-row{
        align-items:flex-start;
        flex-direction:column;
    }

    .mr-nav-actions{
        margin-left:0;
        flex-wrap:wrap;
    }
}



/* MR_8096_IMAGE_MODAL_V1 */

.preview{
    cursor:zoom-in;
}

body.mr-image-modal-open{
    overflow:hidden;
}

.mr-image-modal[hidden]{
    display:none !important;
}

.mr-image-modal{
    position:fixed;
    inset:0;
    z-index:99999;

    display:flex;
    align-items:center;
    justify-content:center;

    padding:20px;

    background:
        rgba(
            0,
            0,
            0,
            .82
        );

    backdrop-filter:
        blur(3px);
}

.mr-image-modal-panel{
    width:min(
        1100px,
        96vw
    );

    max-height:94vh;

    display:flex;
    flex-direction:column;

    overflow:hidden;

    background:#0d1821;

    border:
        1px solid
        #385063;

    border-radius:9px;

    box-shadow:
        0 20px 60px
        rgba(0,0,0,.65);
}

.mr-image-modal-header{
    flex:0 0 auto;

    display:flex;
    align-items:center;

    gap:12px;

    padding:
        10px
        12px;

    background:#132330;

    border-bottom:
        1px solid
        #314657;
}

.mr-image-modal-title{
    min-width:0;
    flex:1;

    color:#edf5fb;

    font-size:13px;
    font-weight:700;

    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
}

.mr-image-modal-close{
    appearance:none;

    width:34px;
    height:30px;

    flex:0 0 auto;

    border:
        1px solid
        #4a6173;

    border-radius:6px;

    background:#182b3a;

    color:#fff;

    font-size:21px;
    line-height:24px;

    cursor:pointer;
}

.mr-image-modal-close:hover{
    background:#254257;
}

.mr-image-modal-body{
    flex:1 1 auto;

    min-height:0;

    padding:10px;

    overflow:auto;

    background:#091219;
}

.mr-image-modal-img{
    display:block;

    width:auto;
    height:auto;

    max-width:100%;
    max-height:82vh;

    margin:auto;

    object-fit:contain;

    border:
        1px solid
        #263c4d;

    border-radius:5px;

    background:#070d11;
}

@media(max-width:700px){

    .mr-image-modal{
        padding:8px;
    }

    .mr-image-modal-panel{
        width:98vw;
        max-height:96vh;
    }

    .mr-image-modal-body{
        padding:5px;
    }

    .mr-image-modal-img{
        max-height:86vh;
    }
}


</style>
</head>

<body>

<header>

<div class="mr-title-row">

    <h1>☄️ MeteorRadio — Ulubione detekcje</h1>

    <div class="mr-nav-actions">

        <a
            class="mr-nav-btn"
            href="#" onclick="location.href='http://'+location.hostname+':8094/';return false;"
        >
            MeteorRadio
        </a>

        <a
            class="mr-nav-btn"
            href="#" onclick="location.href='http://'+location.hostname+':8097/';return false;"
        >
            Statystyki
        </a>

        <button
            class="mr-nav-btn"
            type="button"
            onclick="location.reload()"
        >
            ↻ Odśwież
        </button>

    </div>

</div>

<div class="toolbar">

<button class="filter active" data-filter="all">1–7</button>

<button class="filter" data-filter="1">1</button>
<button class="filter" data-filter="2">2</button>
<button class="filter" data-filter="3">3</button>
<button class="filter" data-filter="4">4</button>
<button class="filter" data-filter="5">5</button>
<button class="filter" data-filter="6">6</button>
<button class="filter" data-filter="7">7</button>

<button class="filter" data-filter="liked">
❤️ ulubione
</button>

<span id="summary">
ładowanie…
</span>

<!-- MR_8096_BULK_DELETE_UNLIKED_V2 -->
<button
    id="bulkDeleteUnlikedBtn"
    class="bulk-delete-unliked"
    type="button"
    title="Usuń na stałe wszystkie niepolubiane detekcje"
>
    Usuń wszystkie niepolubiane
</button>

</div>

</header>

<main id="grid" class="grid"></main>

<!-- MR_8096_IMAGE_MODAL_V1 -->
<div
    id="mrImageModal"
    class="mr-image-modal"
    hidden
    aria-hidden="true"
>

    <div
        class="mr-image-modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mrImageModalTitle"
    >

        <div class="mr-image-modal-header">

            <div
                id="mrImageModalTitle"
                class="mr-image-modal-title"
            >
                Podgląd detekcji
            </div>

            <button
                id="mrImageModalClose"
                class="mr-image-modal-close"
                type="button"
                title="Zamknij"
                aria-label="Zamknij"
            >
                ×
            </button>

        </div>

        <div class="mr-image-modal-body">

            <img
                id="mrImageModalImg"
                class="mr-image-modal-img"
                alt="Powiększony waterfall detekcji"
            >

        </div>

    </div>

</div>

<script>

let DATA={
    items:[],
    counts:{}
};

let FILTER="all";


/* MR_8096_AUDIO_V3 */

let MR_AUDIO=null;
let MR_AUDIO_BUTTON=null;


function mrStopAudio(){

    const audio=
        MR_AUDIO;

    const button=
        MR_AUDIO_BUTTON;


    MR_AUDIO=null;
    MR_AUDIO_BUTTON=null;


    if(audio){

        try{
            audio.pause();
        }catch(_){}

        try{

            audio.removeAttribute(
                "src"
            );

            audio.load();

        }catch(_){}
    }


    if(button){

        button.disabled=false;

        button.classList.remove(
            "playing"
        );

        button.textContent=
            "🔊";

        button.title=
            "Odsłuch USB / Doppler";
    }
}




/* MR_8096_IMAGE_MODAL_V1 */

function mrOpenImageModal(
    file,
    src
){

    const modal=
        document.getElementById(
            "mrImageModal"
        );

    const image=
        document.getElementById(
            "mrImageModalImg"
        );

    const title=
        document.getElementById(
            "mrImageModalTitle"
        );


    if(
        !modal
        ||
        !image
        ||
        !title
    ){
        return;
    }


    const item=(
        Array.isArray(DATA.items)
        ?
        DATA.items.find(
            x=>
                x
                &&
                x.file
                ===
                file
        )
        :
        null
    );


    if(
        item
        &&
        item.score
        !==
        undefined
    ){

        title.textContent=
            `Ocena ${item.score} · ${file}`;

    }else{

        title.textContent=
            file
            ||
            "Podgląd detekcji";
    }


    /*
     * Używamy dokładnie TEGO SAMEGO pełnego PNG,
     * który jest już załadowany jako miniatura.
     *
     * Nie uruchamiamy nowego FFT/renderera.
     */

    image.src=src;


    modal.hidden=false;

    modal.setAttribute(
        "aria-hidden",
        "false"
    );


    document.body.classList.add(
        "mr-image-modal-open"
    );


    const close=
        document.getElementById(
            "mrImageModalClose"
        );

    if(close){
        close.focus();
    }
}


function mrCloseImageModal(){

    const modal=
        document.getElementById(
            "mrImageModal"
        );

    const image=
        document.getElementById(
            "mrImageModalImg"
        );


    if(!modal){
        return;
    }


    modal.hidden=true;

    modal.setAttribute(
        "aria-hidden",
        "true"
    );


    document.body.classList.remove(
        "mr-image-modal-open"
    );


    /*
     * Czyścimy tylko referencję w dużym oknie.
     * Miniatura i cache przeglądarki pozostają.
     */

    if(image){
        image.removeAttribute(
            "src"
        );
    }
}


document.addEventListener(
    "click",
    event=>{

        const target=
            event.target;


        if(
            !target
            ||
            !target.closest
        ){
            return;
        }


        /*
         * Kliknięcie MINIATURY.
         */

        const preview=
            target.closest(
                "img.preview"
            );


        if(preview){

            const card=
                preview.closest(
                    "article.card"
                );


            const file=(
                card
                &&
                card.dataset
                ?
                card.dataset.file
                :
                ""
            );


            const src=(
                preview.currentSrc
                ||
                preview.src
            );


            if(src){

                event.preventDefault();

                mrOpenImageModal(
                    file,
                    src
                );
            }

            return;
        }


        /*
         * X w modalu.
         */

        if(
            target.closest(
                "#mrImageModalClose"
            )
        ){

            event.preventDefault();

            mrCloseImageModal();

            return;
        }


        /*
         * Kliknięcie ciemnego tła poza panelem.
         */

        const modal=
            document.getElementById(
                "mrImageModal"
            );


        if(
            modal
            &&
            target
            ===
            modal
        ){

            mrCloseImageModal();
        }
    }
);


document.addEventListener(
    "keydown",
    event=>{

        if(
            event.key
            !==
            "Escape"
        ){
            return;
        }


        const modal=
            document.getElementById(
                "mrImageModal"
            );


        if(
            modal
            &&
            !modal.hidden
        ){

            event.preventDefault();

            mrCloseImageModal();
        }
    }
);


function esc(s){

    return String(s)
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll('"',"&quot;");
}


function remainingText(seconds){

    seconds=Math.max(
        0,
        Math.floor(seconds)
    );

    const d=Math.floor(
        seconds/86400
    );

    const h=Math.floor(
        (
            seconds%86400
        )
        /
        3600
    );

    const m=Math.floor(
        (
            seconds%3600
        )
        /
        60
    );


    if(d>0){
        return `${d} d ${h} h`;
    }

    if(h>0){
        return `${h} h ${m} min`;
    }

    return `${m} min`;
}


function visible(item){

    if(FILTER==="all"){
        return true;
    }

    if(FILTER==="liked"){
        return item.liked;
    }

    return (
        Number(FILTER)
        ===
        Number(item.score)
    );
}


function render(){

    mrStopAudio();

    const grid=
        document.getElementById(
            "grid"
        );

    const rows=DATA.items.filter(
        visible
    );


    document.getElementById(
        "summary"
    ).textContent=
        `detekcje: ${DATA.total} · ulubione: ${DATA.liked}`;


    if(!rows.length){

        grid.innerHTML=
            `<div class="empty">Brak detekcji w tym filtrze.</div>`;

        return;
    }


    grid.innerHTML=rows.map(
        item=>{

            const file=
                encodeURIComponent(
                    item.file
                );

            const ret=item.liked
                ?
                `<div class="retention forever">❤️ zachowana bezterminowo</div>`
                :
                `<div class="retention">auto-delete za: ${remainingText(item.remaining_seconds)}</div>`;


            return `
            <article
                class="card ${item.liked ? "liked":""}"
                data-file="${esc(item.file)}"
            >

                <img
                    class="preview"
                    loading="lazy"
                    src="/image?file=${file}"
                    alt=""
                >

                <div class="cardbody">

                    <div class="title-row">

                        <div class="score">
                            Ocena ${item.score}
                        </div>

                        <a
                            class="iq-download"
                            href="/smp-original?file=${file}"
                            title="Pobierz oryginalny SMP / complex IQ"
                            aria-label="Pobierz oryginalny SMP / complex IQ"
                        >IQ</a>

                        <a
                            class="audio-download"
                            href="/audio-original?file=${file}"
                            title="Pobierz oryginalny niefiltrowany WAV"
                            aria-label="Pobierz oryginalny niefiltrowany WAV"
                        >⬇</a>

                        <button
                            type="button"
                            class="audio-play"
                            title="Odsłuch USB / Doppler"
                            aria-label="Odsłuch USB / Doppler"
                            data-file="${esc(item.file)}"
                        >🔊</button>

                        <button
                            type="button"
                            class="delete"
                            title="Usuń detekcję na stałe"
                            data-file="${esc(item.file)}"
                        >✕</button>

                        <button
                            type="button"
                            class="heart ${item.liked ? "on":"off"}"
                            title="${item.liked ? "Usuń z ulubionych":"Zachowaj bezterminowo"}"
                            data-file="${esc(item.file)}"
                        >${item.liked ? "❤️":"♡"}</button>

                    </div>

                    <div class="filename">
                        ${esc(item.file)}
                    </div>

                    ${ret}

                </div>

            </article>`;
        }
    ).join("");


    /* MR_8096_AUDIO_V3 */

    document.querySelectorAll(
        ".audio-play"
    ).forEach(

        b=>{

            b.onclick=async()=>{

                const file=
                    b.dataset.file;


                /*
                 * Ten sam przycisk:
                 * play -> stop.
                 */
                if(
                    MR_AUDIO_BUTTON
                    ===
                    b
                ){

                    mrStopAudio();

                    return;
                }


                /*
                 * Jeden klip naraz.
                 */
                mrStopAudio();


                b.disabled=true;

                b.textContent=
                    "…";

                b.title=
                    "Przygotowuję USB audio…";


                const audio=
                    new Audio();


                audio.preload=
                    "none";

                audio.volume=
                    0.90;


                audio.src=
                    "/audio?file="
                    +
                    encodeURIComponent(
                        file
                    );


                MR_AUDIO=
                    audio;

                MR_AUDIO_BUTTON=
                    b;


                audio.onplaying=()=>{

                    if(
                        MR_AUDIO
                        !==
                        audio
                    ){
                        return;
                    }


                    b.disabled=false;

                    b.classList.add(
                        "playing"
                    );

                    b.textContent=
                        "⏹";

                    b.title=
                        "Zatrzymaj odsłuch";
                };


                audio.onended=()=>{

                    if(
                        MR_AUDIO
                        ===
                        audio
                    ){

                        mrStopAudio();
                    }
                };


                audio.onerror=()=>{

                    if(
                        MR_AUDIO
                        !==
                        audio
                    ){
                        return;
                    }


                    mrStopAudio();


                    alert(
                        "Nie udało się odtworzyć "
                        +
                        "audio tej detekcji."
                    );
                };


                try{

                    await audio.play();

                }catch(e){

                    if(
                        MR_AUDIO
                        ===
                        audio
                    ){

                        mrStopAudio();

                        alert(
                            "Nie udało się uruchomić odsłuchu:\n\n"
                            +
                            (
                                e
                                &&
                                e.message
                                ?
                                e.message
                                :
                                String(e)
                            )
                        );
                    }
                }
            };
        }
    );


    document.querySelectorAll(
        ".heart"
    ).forEach(
        b=>{

            b.onclick=async()=>{

                b.disabled=true;

                try{

                    const r=await fetch(
                        "/api/toggle",
                        {
                            method:"POST",
                            headers:{
                                "Content-Type":
                                    "application/json"
                            },
                            body:JSON.stringify(
                                {
                                    file:
                                        b.dataset.file
                                }
                            )
                        }
                    );

                    const d=await r.json();

                    if(
                        !r.ok
                        ||
                        !d.ok
                    ){
                        throw new Error(
                            d.error
                            ||
                            `HTTP ${r.status}`
                        );
                    }

                    await loadData();

                }catch(e){

                    alert(
                        "Błąd ulubionych:\n\n"
                        +
                        e.message
                    );

                    b.disabled=false;
                }
            };
        }
    );


    document.querySelectorAll(
        ".delete"
    ).forEach(
        b=>{

            b.onclick=async()=>{

                const file=
                    b.dataset.file;

                const ok=confirm(
                    "USUNĄĆ DETEKCJĘ NA STAŁE?\n\n"
                    +
                    file
                    +
                    "\n\n"
                    +
                    "Usunięte zostaną:\n"
                    +
                    "• SMP\n"
                    +
                    "• cache\n"
                    +
                    "• ocena ze score-index\n"
                    +
                    "• ❤️\n"
                    +
                    "• stan retencji"
                );

                if(!ok){
                    return;
                }


                b.disabled=true;
                b.textContent="…";


                try{

                    const r=await fetch(
                        "/api/delete",
                        {
                            method:"POST",
                            headers:{
                                "Content-Type":
                                    "application/json"
                            },
                            body:JSON.stringify(
                                {
                                    file:file
                                }
                            )
                        }
                    );

                    const d=await r.json();

                    if(
                        !r.ok
                        ||
                        !d.ok
                    ){

                        throw new Error(
                            d.error
                            ||
                            `HTTP ${r.status}`
                        );
                    }

                    await loadData();

                }catch(e){

                    alert(
                        "Nie udało się usunąć:\n\n"
                        +
                        e.message
                    );

                    b.disabled=false;
                    b.textContent="✕";
                }
            };
        }
    );
}


async function loadData(){

    const r=await fetch(
        "/api/data",
        {
            cache:"no-store"
        }
    );

    DATA=await r.json();

    render();
}



/* MR_8096_BULK_DELETE_UNLIKED_V2 */

async function bulkDeleteUnliked(){

    const button=
        document.getElementById(
            "bulkDeleteUnlikedBtn"
        );


    const victims=(
        Array.isArray(DATA.items)
        ?
        DATA.items
        :
        []
    ).filter(
        item=>
            item
            &&
            !item.liked
            &&
            item.file
    );


    if(!victims.length){

        alert(
            "Nie ma żadnych niepolubianych detekcji do usunięcia."
        );

        return;
    }


    const confirmed=confirm(
        "Czy na pewno chcesz TRWALE usunąć wszystkie "
        +
        "niepolubiane detekcje?\n\n"
        +
        `Liczba do usunięcia: ${victims.length}\n\n`
        +
        "Polubione ❤️ pozostaną bez zmian.\n"
        +
        "Usuniętych danych nie będzie można odzyskać."
    );


    if(!confirmed){
        return;
    }


    button.disabled=true;

    const originalText=
        "Usuń wszystkie niepolubiane";

    let done=0;


    try{

        for(
            const item
            of victims
        ){

            button.textContent=
                `Usuwam ${done}/${victims.length}…`;


            const r=await fetch(
                "/api/delete",
                {
                    method:"POST",

                    headers:{
                        "Content-Type":
                            "application/json"
                    },

                    body:JSON.stringify(
                        {
                            file:item.file
                        }
                    ),

                    cache:"no-store"
                }
            );


            let d={};

            try{
                d=await r.json();
            }catch(_){
                d={};
            }


            if(
                !r.ok
                ||
                !d.ok
            ){

                throw new Error(
                    (
                        d.error
                        ||
                        `HTTP ${r.status}`
                    )
                    +
                    "\n\n"
                    +
                    item.file
                );
            }


            done++;


            /*
             * Usuwamy rekord również z lokalnego DATA,
             * aby nawet przy późniejszym problemie
             * przeglądarka nie próbowała ponownie
             * kasować już usuniętej detekcji.
             */
            DATA.items=
                DATA.items.filter(
                    x=>
                        x.file
                        !==
                        item.file
                );


            if(
                Number.isFinite(
                    Number(DATA.total)
                )
            ){
                DATA.total=
                    Math.max(
                        0,
                        Number(DATA.total)-1
                    );
            }
        }


        button.textContent=
            `Usunięto ${done}/${victims.length}`;


        await loadData();


        alert(
            `Gotowe.\n\nUsunięto ${done} niepolubianych detekcji.\n\n`
            +
            "Polubione ❤️ nie zostały ruszone."
        );


    }catch(e){

        /*
         * Np. scoring ruszył w trakcie.
         * manual_delete() zwróci wtedy blokadę
         * i NIE forsujemy dalszych DELETE.
         */

        try{
            await loadData();
        }catch(_){
            try{
                render();
            }catch(__){}
        }


        alert(
            "Usuwanie zostało zatrzymane.\n\n"
            +
            `Usunięto: ${done}/${victims.length}\n\n`
            +
            "Powód:\n"
            +
            (
                e
                &&
                e.message
                ?
                e.message
                :
                String(e)
            )
            +
            "\n\n"
            +
            "Pozostałe niepolubiane detekcje nie zostały usunięte."
        );


    }finally{

        button.disabled=false;
        button.textContent=
            originalText;
    }
}


const bulkDeleteUnlikedButton=
    document.getElementById(
        "bulkDeleteUnlikedBtn"
    );


if(bulkDeleteUnlikedButton){

    bulkDeleteUnlikedButton.onclick=
        bulkDeleteUnliked;
}


document.querySelectorAll(
    ".filter"
).forEach(
    b=>{

        b.onclick=()=>{

            FILTER=b.dataset.filter;

            document.querySelectorAll(
                ".filter"
            ).forEach(
                x=>
                    x.classList.remove(
                        "active"
                    )
            );

            b.classList.add(
                "active"
            );

            render();
        };
    }
);


loadData();


/*
 * Jeden lekki refresh panelu.
 * Bez MutationObserverów.
 */
void 0; /* MR_8096_AUTO_REFRESH_DISABLED_V1 */

</script>


<!-- MR_8096_DURATION_UI_V1 -->
<script>
(() => {

    const DURATION_MARK =
        "mrDurationBound";


    const observer =
        new IntersectionObserver(
            entries => {

                for (const entry of entries) {

                    if (!entry.isIntersecting) {
                        continue;
                    }

                    observer.unobserve(
                        entry.target
                    );

                    loadDuration(
                        entry.target
                    );
                }
            },
            {
                rootMargin: "250px"
            }
        );


    function scoreElement(
        iq
    ) {

        let root=
            iq.parentElement;


        for (
            let level=0;
            root && level<7;
            level++,
            root=root.parentElement
        ) {

            const all=[
                root,
                ...root.querySelectorAll("*")
            ];


            for (
                const el
                of
                all
            ) {

                if (
                    el.children.length
                    !==
                    0
                ) {
                    continue;
                }


                const text=(
                    el.textContent
                    ||
                    ""
                ).trim();


                if (
                    /^Ocena\s+[1-7]$/
                    .test(
                        text
                    )
                ) {

                    return el;
                }
            }
        }


        return null;
    }


    async function loadDuration(
        iq
    ) {

        const score=
            scoreElement(
                iq
            );


        if (!score) {
            return;
        }


        if (
            score.parentElement
            &&
            score.parentElement
                .querySelector(
                    ".mr-detection-duration"
                )
        ) {

            return;
        }


        const href=
            iq.getAttribute(
                "href"
            )
            ||
            "";


        let file="";


        try {

            const url=
                new URL(
                    href,
                    window.location.href
                );

            file=
                url.searchParams.get(
                    "file"
                )
                ||
                "";

        } catch (_) {

            return;
        }


        if (!file) {
            return;
        }


        try {

            const r=
                await fetch(
                    "/duration?v=2&file="
                    +
                    encodeURIComponent(
                        file
                    ),
                    {
                        cache:
                            "force-cache"
                    }
                );


            if (!r.ok) {
                return;
            }


            const d=
                await r.json();


            const seconds=
                Number(
                    d.seconds
                );


            if (
                !Number.isFinite(
                    seconds
                )
                ||
                seconds <= 0
            ) {

                return;
            }


            const span=
                document.createElement(
                    "span"
                );


            span.className=
                "mr-detection-duration";


            span.style.marginLeft=
                "6px";

            span.style.fontSize=
                "12px";

            span.style.fontWeight=
                "500";

            span.style.color=
                "#9aa6b2";

            span.style.whiteSpace=
                "nowrap";


            span.textContent=
                ""
                +
                seconds
                    .toFixed(2)
                    .replace(
                        ".",
                        ","
                    )
                +
                " s";


            score.insertAdjacentElement(
                "afterend",
                span
            );


        } catch (_) {

            /*
             * Brak wartości nie może
             * wpłynąć na działanie karty.
             */
        }
    }


    function scan() {

        document
            .querySelectorAll(
                "a.iq-download"
            )
            .forEach(
                iq => {

                    if (
                        iq.dataset[
                            DURATION_MARK
                        ]
                    ) {
                        return;
                    }


                    iq.dataset[
                        DURATION_MARK
                    ]="1";


                    observer.observe(
                        iq
                    );
                }
            );
    }


    scan();


    const mutations=
        new MutationObserver(
            () => {
                scan();
            }
        );


    mutations.observe(
        document.body,
        {
            childList: true,
            subtree: true
        }
    );

})();
</script>


<!-- MR_8096_TRIGGER_TIME_V5_FRONTEND -->
<script>
(() => {

    const FLAG =
        "mrTriggerTimeV5";


    async function loadTriggerTime(
        card
    ) {

        const name =
            String(
                card.dataset.file
                ||
                ""
            );


        const line =
            card.querySelector(
                ".filename"
            );


        if (
            !name
            ||
            !line
        ) {

            return;
        }


        /*
         * Do czasu odpowiedzi API zostaje
         * obecna nazwa pliku.
         *
         * Przy błędzie również zostaje,
         * więc karta nadal jest użyteczna.
         */

        line.title =
            "Plik: "
            +
            name;


        try {

            const response =
                await fetch(
                    "/trigger-time?v=5&file="
                    +
                    encodeURIComponent(
                        name
                    ),
                    {
                        cache:
                            "force-cache"
                    }
                );


            if (
                !response.ok
            ) {

                return;
            }


            const data =
                await response.json();


            if (
                !data
                ||
                !data.ok
                ||
                !data.display
            ) {

                return;
            }


            line.textContent =
                String(
                    data.display
                );


            line.title =
                "Trigger: "
                +
                String(
                    data.trigger_time
                    ||
                    data.display
                )
                +
                "\nPlik: "
                +
                name;


        } catch (_) {

            /*
             * Nic nie zmieniamy —
             * nazwa SMP pozostaje widoczna.
             */
        }
    }


    const observer =
        new IntersectionObserver(
            entries => {

                for (
                    const entry
                    of entries
                ) {

                    if (
                        !entry.isIntersecting
                    ) {

                        continue;
                    }


                    observer.unobserve(
                        entry.target
                    );


                    loadTriggerTime(
                        entry.target
                    );
                }
            },
            {
                rootMargin:
                    "250px"
            }
        );


    function scan() {

        document
            .querySelectorAll(
                ".card[data-file]"
            )
            .forEach(
                card => {

                    if (
                        card.dataset[
                            FLAG
                        ]
                        ===
                        "1"
                    ) {

                        return;
                    }


                    card.dataset[
                        FLAG
                    ] =
                        "1";


                    observer.observe(
                        card
                    );
                }
            );
    }


    scan();


    const mutations =
        new MutationObserver(
            scan
        );


    mutations.observe(
        document.body,
        {
            childList:
                true,

            subtree:
                true
        }
    );

})();
</script>

</body>
</html>
'''


class Handler(
    BaseHTTPRequestHandler
):


    def log_message(
        self,
        fmt,
        *args
    ):

        print(
            "[8096]",
            fmt % args,
            flush=True
        )


    def send_json(
        self,
        obj,
        code=200
    ):

        raw=json.dumps(
            obj,
            ensure_ascii=False
        ).encode(
            "utf-8"
        )

        self.send_response(
            code
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(raw))
        )



        # MR_LIKES_CORS_PUBLIC_V2
        #
        # Public build:
        # accept port 8094 on the same hostname
        # as the current request. Additional
        # origins may be supplied through:
        #
        # METEORRADIO_ALLOWED_ORIGINS
        #
        _origin=self.headers.get(
            "Origin"
        )

        _host_header=self.headers.get(
            "Host",
            ""
        )

        _same_host=False

        if _origin:

            try:

                _origin_url=urlsplit(
                    _origin
                )

                _host_url=urlsplit(
                    "http://"
                    +
                    _host_header
                )

                _origin_port=(
                    _origin_url.port
                    or
                    (
                        443
                        if
                        _origin_url.scheme
                        ==
                        "https"
                        else
                        80
                    )
                )

                _same_host=bool(
                    _origin_url.hostname
                    and
                    _host_url.hostname
                    and
                    _origin_url.hostname.lower()
                    ==
                    _host_url.hostname.lower()
                    and
                    _origin_port
                    ==
                    8094
                )

            except Exception:

                _same_host=False


        _extra_origins={
            item.strip()
            for item
            in os.environ.get(
                "METEORRADIO_ALLOWED_ORIGINS",
                ""
            ).split(",")
            if item.strip()
        }


        if (
            _origin
            and
            (
                _same_host
                or
                _origin
                in
                _extra_origins
            )
        ):

            self.send_header(
                "Access-Control-Allow-Origin",
                _origin
            )

            self.send_header(
                "Vary",
                "Origin"
            )

        self.end_headers()

        self.wfile.write(
            raw
        )


    def send_html(
        self,
        text
    ):

        raw=text.encode(
            "utf-8"
        )

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(raw))
        )

        self.end_headers()

        self.wfile.write(
            raw
        )


    def do_GET(self):

        parsed=urllib.parse.urlparse(
            self.path
        )

        path=parsed.path

        q=urllib.parse.parse_qs(
            parsed.query
        )


        if path == "/":

            return self.send_html(
                HTML
            )


        # MR_API_LIST_COMPAT_V3
        #
        # /api/list to kompatybilność dla 8094.
        # /api/data pozostaje głównym API 8096.
        #
        if path in (
            "/api/data",
            "/api/list",
        ):

            return self.send_json(
                snapshot()
            )


        if path == "/healthz":

            return self.send_json(
                {
                    "ok":True,
                    "service":
                        "meteorradio-likes",
                    "policy":
                        "score-1-7-ttl"
                }
            )


        # MR_8096_DURATION_UI_V1
        # MR_8096_TOTAL_CAPTURE_DURATION_V2
        # MR_8096_TRIGGER_TIME_V5_BACKEND
        if path == "/trigger-time":

            import ast as _ast
            import datetime as _datetime
            import json as _json
            import math as _math
            import struct as _struct
            import sys as _sys
            import zipfile as _zipfile


            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )


            try:

                name=safe_name(
                    name
                )


                src=RADAR/name


                if not src.is_file():

                    raise FileNotFoundError(
                        name
                    )


                def _mr_npy_header(
                    fp
                ):

                    magic=fp.read(
                        6
                    )


                    if (
                        magic
                        !=
                        bytes(
                            (147,)
                        )
                        +
                        b"NUMPY"
                    ):

                        raise ValueError(
                            "invalid NPY magic"
                        )


                    version=fp.read(
                        2
                    )


                    if len(
                        version
                    ) != 2:

                        raise ValueError(
                            "invalid NPY version"
                        )


                    major=version[0]


                    if major == 1:

                        raw_len=fp.read(
                            2
                        )


                        if len(
                            raw_len
                        ) != 2:

                            raise ValueError(
                                "short NPY header length"
                            )


                        header_len=(
                            _struct.unpack(
                                "<H",
                                raw_len
                            )[0]
                        )


                    elif major in (
                        2,
                        3
                    ):

                        raw_len=fp.read(
                            4
                        )


                        if len(
                            raw_len
                        ) != 4:

                            raise ValueError(
                                "short NPY header length"
                            )


                        header_len=(
                            _struct.unpack(
                                "<I",
                                raw_len
                            )[0]
                        )


                    else:

                        raise ValueError(
                            "unsupported NPY version"
                        )


                    raw_header=fp.read(
                        header_len
                    )


                    if len(
                        raw_header
                    ) != header_len:

                        raise ValueError(
                            "short NPY header"
                        )


                    encoding=(
                        "utf-8"
                        if major == 3
                        else
                        "latin1"
                    )


                    return _ast.literal_eval(
                        raw_header
                        .decode(
                            encoding
                        )
                        .strip()
                    )


                def _mr_npy_text_scalar(
                    fp
                ):

                    header=_mr_npy_header(
                        fp
                    )


                    descr=str(
                        header.get(
                            "descr",
                            ""
                        )
                    )


                    shape=header.get(
                        "shape",
                        ()
                    )


                    count=(
                        _math.prod(
                            shape
                        )
                        if shape
                        else
                        1
                    )


                    if count != 1:

                        raise ValueError(
                            "trigger_time must be scalar"
                        )


                    if descr.startswith(
                        "<U"
                    ):

                        chars=int(
                            descr[2:]
                        )

                        value=(
                            fp.read(
                                chars * 4
                            )
                            .decode(
                                "utf-32-le"
                            )
                        )


                    elif descr.startswith(
                        ">U"
                    ):

                        chars=int(
                            descr[2:]
                        )

                        value=(
                            fp.read(
                                chars * 4
                            )
                            .decode(
                                "utf-32-be"
                            )
                        )


                    elif descr.startswith(
                        "=U"
                    ):

                        chars=int(
                            descr[2:]
                        )


                        encoding=(
                            "utf-32-le"
                            if _sys.byteorder
                            ==
                            "little"
                            else
                            "utf-32-be"
                        )


                        value=(
                            fp.read(
                                chars * 4
                            )
                            .decode(
                                encoding
                            )
                        )


                    elif descr.startswith(
                        "|S"
                    ):

                        chars=int(
                            descr[2:]
                        )

                        value=(
                            fp.read(
                                chars
                            )
                            .decode(
                                "utf-8",
                                errors="replace"
                            )
                        )


                    else:

                        raise ValueError(
                            "unsupported trigger dtype: "
                            +
                            descr
                        )


                    return (
                        value
                        .rstrip(
                            "\x00"
                        )
                        .strip()
                    )


                with _zipfile.ZipFile(
                    src,
                    "r"
                ) as archive:


                    names=set(
                        archive.namelist()
                    )


                    selected=None


                    #
                    # Pierwszy wybór:
                    # rzeczywisty trigger detekcji.
                    #
                    # Fallback:
                    # trigger całego eventu V3.
                    #

                    for candidate in (
                        "trigger_time.npy",
                        "adaptive_event_trigger_time.npy",
                    ):

                        if candidate in names:

                            selected=candidate

                            break


                    if selected is None:

                        raise KeyError(
                            "trigger_time"
                        )


                    with archive.open(
                        selected,
                        "r"
                    ) as fp:

                        trigger=(
                            _mr_npy_text_scalar(
                                fp
                            )
                        )


                if not trigger:

                    raise ValueError(
                        "empty trigger_time"
                    )


                dt=(
                    _datetime.datetime
                    .fromisoformat(
                        trigger.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )


                display=(
                    dt.strftime(
                        "%d.%m.%Y %H:%M:%S"
                    )
                )


                body=_json.dumps(
                    {
                        "ok":
                            True,

                        "trigger_time":
                            trigger,

                        "display":
                            display,

                        "field":
                            selected[:-4],
                    },
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":"
                    ),
                ).encode(
                    "utf-8"
                )


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8"
                )


                self.send_header(
                    "Content-Length",
                    str(
                        len(body)
                    )
                )


                self.send_header(
                    "Cache-Control",
                    "private, max-age=86400"
                )


                self.end_headers()


                self.wfile.write(
                    body
                )


                return


            except FileNotFoundError:

                self.send_error(
                    404
                )

                return


            except (
                KeyError,
                ValueError,
                TypeError,
                _zipfile.BadZipFile,
            ) as e:

                print(
                    "TRIGGER_TIME_PARSE_ERROR",
                    name,
                    repr(e),
                    flush=True
                )


                self.send_error(
                    422
                )


                return


            except Exception as e:

                print(
                    "TRIGGER_TIME_HTTP_ERROR",
                    name,
                    repr(e),
                    flush=True
                )


                self.send_error(
                    500
                )


                return

        if path == "/duration":

            import ast as _ast
            import json as _json
            import math as _math
            import struct as _struct
            import zipfile as _zipfile


            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )


            try:

                name=safe_name(
                    name
                )


                src=RADAR/name


                if not src.is_file():

                    raise FileNotFoundError(
                        name
                    )


                def _read_npy_header(
                    _fp
                ):

                    _magic=_fp.read(
                        6
                    )


                    _expected=(
                        bytes(
                            (147,)
                        )
                        +
                        b"NUMPY"
                    )


                    if _magic != _expected:

                        raise ValueError(
                            "invalid NPY magic"
                        )


                    _version=_fp.read(
                        2
                    )


                    if len(
                        _version
                    ) != 2:

                        raise ValueError(
                            "invalid NPY version"
                        )


                    _major=_version[0]


                    if _major == 1:

                        _raw=_fp.read(
                            2
                        )

                        if len(_raw) != 2:
                            raise ValueError(
                                "invalid header length"
                            )

                        _hlen=_struct.unpack(
                            "<H",
                            _raw
                        )[0]


                    elif _major in (
                        2,
                        3
                    ):

                        _raw=_fp.read(
                            4
                        )

                        if len(_raw) != 4:
                            raise ValueError(
                                "invalid header length"
                            )

                        _hlen=_struct.unpack(
                            "<I",
                            _raw
                        )[0]


                    else:

                        raise ValueError(
                            "unsupported NPY version"
                        )


                    _raw_header=_fp.read(
                        _hlen
                    )


                    if len(
                        _raw_header
                    ) != _hlen:

                        raise ValueError(
                            "short NPY header"
                        )


                    _encoding=(
                        "utf-8"
                        if _major == 3
                        else
                        "latin1"
                    )


                    return _ast.literal_eval(
                        _raw_header
                        .decode(
                            _encoding
                        )
                        .strip()
                    )


                def _read_npy_scalar(
                    _fp
                ):

                    _h=_read_npy_header(
                        _fp
                    )


                    _descr=str(
                        _h[
                            "descr"
                        ]
                    )


                    if (
                        _descr
                        and
                        _descr[0]
                        in "<>=|"
                    ):

                        _endian=_descr[0]
                        _core=_descr[1:]

                    else:

                        _endian="="
                        _core=_descr


                    if len(
                        _core
                    ) < 2:

                        raise ValueError(
                            "invalid scalar dtype"
                        )


                    _kind=_core[0]
                    _size=int(
                        _core[1:]
                    )


                    _formats={
                        ("f",4): "f",
                        ("f",8): "d",
                        ("i",4): "i",
                        ("i",8): "q",
                        ("u",4): "I",
                        ("u",8): "Q",
                    }


                    _code=_formats.get(
                        (
                            _kind,
                            _size
                        )
                    )


                    if _code is None:

                        raise ValueError(
                            "unsupported scalar dtype"
                        )


                    if _endian == ">":
                        _prefix=">"
                    elif _endian == "<":
                        _prefix="<"
                    else:
                        _prefix="="


                    _raw=_fp.read(
                        _size
                    )


                    if len(
                        _raw
                    ) != _size:

                        raise ValueError(
                            "short scalar data"
                        )


                    return _struct.unpack(
                        _prefix + _code,
                        _raw
                    )[0]


                #
                # Czytamy tylko:
                #
                # samples.npy -> HEADER / shape
                # sample_rate.npy -> pojedynczą wartość
                #
                # Nie ładujemy tablicy IQ.
                #
                with _zipfile.ZipFile(
                    src,
                    "r"
                ) as _zf:


                    with _zf.open(
                        "samples.npy"
                    ) as _fp:

                        _samples_header=(
                            _read_npy_header(
                                _fp
                            )
                        )


                    _shape=tuple(
                        int(_x)
                        for _x
                        in _samples_header[
                            "shape"
                        ]
                    )


                    if not _shape:

                        raise ValueError(
                            "empty samples shape"
                        )


                    _sample_count=(
                        _math.prod(
                            _shape
                        )
                    )


                    with _zf.open(
                        "sample_rate.npy"
                    ) as _fp:

                        _sample_rate=float(
                            _read_npy_scalar(
                                _fp
                            )
                        )


                if (
                    _sample_count <= 0
                    or
                    _sample_rate <= 0
                ):

                    raise ValueError(
                        "invalid capture dimensions"
                    )


                seconds=(
                    float(
                        _sample_count
                    )
                    /
                    _sample_rate
                )


                if (
                    not _math.isfinite(
                        seconds
                    )
                    or
                    seconds <= 0
                ):

                    raise ValueError(
                        "invalid duration"
                    )


                body=_json.dumps(
                    {
                        "ok": True,
                        "seconds": seconds,
                        "source": "samples/sample_rate",
                    },
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":"
                    ),
                ).encode(
                    "utf-8"
                )


                self.send_response(
                    200
                )

                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(
                        len(body)
                    )
                )

                self.send_header(
                    "Cache-Control",
                    "private, max-age=86400"
                )

                self.end_headers()

                self.wfile.write(
                    body
                )

                return


            except FileNotFoundError:

                self.send_error(
                    404
                )

                return


            except (
                ValueError,
                KeyError,
                TypeError,
                _zipfile.BadZipFile,
            ) as e:

                print(
                    "DURATION_PARSE_ERROR",
                    name,
                    repr(e),
                    flush=True
                )

                self.send_error(
                    422
                )

                return


            except Exception as e:

                print(
                    "DURATION_HTTP_ERROR",
                    name,
                    repr(e),
                    flush=True
                )

                self.send_error(
                    500
                )

                return


        # MR_8096_IQ_DOWNLOAD_V1
        if path == "/smp-original":

            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )


            try:

                name=safe_name(
                    name
                )


                p=RADAR/name


                if not p.is_file():

                    raise FileNotFoundError(
                        name
                    )


                size=p.stat().st_size


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "application/octet-stream"
                )


                self.send_header(
                    "Content-Length",
                    str(
                        size
                    )
                )


                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="'
                    +
                    name
                    +
                    '"'
                )


                self.send_header(
                    "Cache-Control",
                    "private, max-age=60"
                )


                self.end_headers()


                #
                # Streaming:
                # bez wczytywania całego SMP do RAM.
                #
                with p.open(
                    "rb"
                ) as f:

                    while True:

                        chunk=f.read(
                            256 * 1024
                        )


                        if not chunk:
                            break


                        self.wfile.write(
                            chunk
                        )


                return


            except ValueError:

                self.send_error(
                    400
                )

                return


            except FileNotFoundError:

                self.send_error(
                    404
                )

                return


            except (
                BrokenPipeError,
                ConnectionResetError,
            ):

                #
                # Użytkownik anulował download.
                #
                return


            except Exception as e:

                print(
                    "SMP_DOWNLOAD_HTTP_ERROR",
                    repr(e),
                    flush=True
                )


                self.send_error(
                    500
                )

                return


        # MR_8096_AUDIO_DOWNLOAD_V1
        if path == "/audio-original":

            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )


            try:

                name=safe_name(
                    name
                )


                p=cached_original_audio(
                    name
                )


                raw=p.read_bytes()


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "audio/wav"
                )


                self.send_header(
                    "Content-Length",
                    str(len(raw))
                )


                self.send_header(
                    "Cache-Control",
                    "private, max-age=86400"
                )


                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="'
                    +
                    p.name
                    +
                    '"'
                )


                self.end_headers()


                self.wfile.write(
                    raw
                )


                return


            except ValueError:

                self.send_error(
                    400
                )

                return


            except FileNotFoundError:

                self.send_error(
                    404
                )

                return


            except Exception as e:

                print(
                    "AUDIO_ORIGINAL_HTTP_ERROR",
                    repr(e),
                    flush=True,
                )


                self.send_error(
                    500
                )

                return


        # MR_8096_AUDIO_V3
        if path == "/audio":

            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )


            try:

                name=safe_name(
                    name
                )


                p=cached_audio(
                    name
                )


                raw=p.read_bytes()


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "audio/wav"
                )


                self.send_header(
                    "Cache-Control",
                    "private, max-age=86400"
                )


                self.send_header(
                    "Content-Length",
                    str(len(raw))
                )


                self.send_header(
                    "Content-Disposition",
                    'inline; filename="'
                    +
                    p.name
                    +
                    '"'
                )


                self.end_headers()


                self.wfile.write(
                    raw
                )


                return


            except ValueError:

                self.send_error(
                    400
                )

                return


            except FileNotFoundError:

                self.send_error(
                    404
                )

                return


            except Exception as e:

                print(
                    "AUDIO_HTTP_ERROR",
                    repr(e),
                    flush=True,
                )


                self.send_error(
                    500
                )

                return


        if path == "/image":

            name=(
                q.get(
                    "file",
                    [""]
                )[0]
            )

            try:

                name=safe_name(
                    name
                )

            except Exception:

                self.send_error(
                    400
                )

                return


            p=cached_image(
                name
            )


            if (
                p is not None
                and
                p.is_file()
            ):

                try:

                    raw=p.read_bytes()

                    mime=(
                        mimetypes.guess_type(
                            p.name
                        )[0]
                        or
                        "image/png"
                    )

                    self.send_response(
                        200
                    )

                    self.send_header(
                        "Content-Type",
                        mime
                    )

                    self.send_header(
                        "Cache-Control",
                        "private, max-age=60"
                    )

                    self.send_header(
                        "Content-Length",
                        str(len(raw))
                    )

                    self.end_headers()

                    self.wfile.write(
                        raw
                    )

                    return

                except Exception:
                    pass


            #
            # Fallback: istniejący renderer 8094.
            #
            try:

                url=(
                    "http://127.0.0.1:8094/"
                    "detection-v5.png?file="
                    +
                    urllib.parse.quote(
                        name
                    )
                    +
                    "&maxhold=1"
                )


                with urllib.request.urlopen(
                    url,
                    timeout=20
                ) as r:

                    raw=r.read()


                self.send_response(
                    200
                )

                self.send_header(
                    "Content-Type",
                    "image/png"
                )

                self.send_header(
                    "Cache-Control",
                    "private, max-age=60"
                )

                self.send_header(
                    "Content-Length",
                    str(len(raw))
                )

                self.end_headers()

                self.wfile.write(
                    raw
                )

                return


            except Exception:

                self.send_error(
                    404
                )

                return


        self.send_error(
            404
        )


    def do_POST(self):

        parsed=urllib.parse.urlparse(
            self.path
        )

        path=parsed.path


        # MR_TOGGLE_QUERY_COMPAT_V4
        #
        # Frontend 8094 używa prostego POST:
        #
        #   /api/toggle?file=SMP_....npz
        #
        # To jest celowo request bez JSON Content-Type,
        # dzięki czemu przeglądarka nie potrzebuje
        # preflight OPTIONS.
        #
        if path == "/api/toggle":

            _query=urllib.parse.parse_qs(
                parsed.query
            )

            _query_file=(
                _query.get(
                    "file"
                )
                or
                [None]
            )[0]

            if _query_file:

                try:

                    return self.send_json(
                        toggle_like(
                            _query_file
                        )
                    )

                except RuntimeError as e:

                    return self.send_json(
                        {
                            "ok":False,
                            "error":str(e)
                        },
                        423
                    )

                except ValueError as e:

                    return self.send_json(
                        {
                            "ok":False,
                            "error":str(e)
                        },
                        409
                    )

                except Exception as e:

                    print(
                        "API_ERROR",
                        repr(e),
                        flush=True
                    )

                    return self.send_json(
                        {
                            "ok":False,
                            "error":repr(e)
                        },
                        500
                    )


        try:

            length=int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
                or 0
            )

        except Exception:

            length=0


        if (
            length < 1
            or
            length > 4096
        ):

            return self.send_json(
                {
                    "ok":False,
                    "error":
                        "invalid body"
                },
                400
            )


        try:

            payload=json.loads(
                self.rfile
                .read(length)
                .decode("utf-8")
            )

        except Exception:

            return self.send_json(
                {
                    "ok":False,
                    "error":
                        "invalid JSON"
                },
                400
            )


        try:

            if path == "/api/toggle":

                return self.send_json(
                    toggle_like(
                        payload.get(
                            "file"
                        )
                    )
                )


            if path == "/api/delete":

                return self.send_json(
                    manual_delete(
                        payload.get(
                            "file"
                        )
                    )
                )


            return self.send_json(
                {
                    "ok":False,
                    "error":
                        "not found"
                },
                404
            )


        except RuntimeError as e:

            return self.send_json(
                {
                    "ok":False,
                    "error":str(e)
                },
                423
            )


        except ValueError as e:

            return self.send_json(
                {
                    "ok":False,
                    "error":str(e)
                },
                409
            )


        except Exception as e:

            print(
                "API_ERROR",
                repr(e),
                flush=True
            )

            return self.send_json(
                {
                    "ok":False,
                    "error":repr(e)
                },
                500
            )


server=ThreadingHTTPServer(
    (
        "0.0.0.0",
        PORT
    ),
    Handler
)

print(
    "MeteorRadio likes 1-7 TTL:",
    f"http://0.0.0.0:{PORT}/",
    flush=True
)

server.serve_forever()
