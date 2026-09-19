#!/usr/bin/env python3

# MR_RETENTION_SCORE_TTL_1_7_V1

import fcntl
import json
import os
import subprocess
import sys
import time

from pathlib import Path


BASE=Path("/home/pi/meteorradio-web")
CACHE=BASE/"cache"
RADAR=Path("/home/pi/radar_data")

INDEX=CACHE/"v562_score_index.json"
LIKES=CACHE/"v562_likes.json"
STATE=CACHE/"v562_retention_state.json"
LOCK=CACHE/"v562_likes.lock"

LEDGER=CACHE/"v562_retention_deleted.jsonl"


POLICY_DAYS={
    1:1,
    2:2,
    3:3,
    4:4,
    5:5,
    6:6,
    7:7,
}

POLICY_SECONDS={
    score:
        days*24*60*60
    for score,days
    in POLICY_DAYS.items()
}


INIT_ONLY=(
    "--init-only"
    in
    sys.argv[1:]
)


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

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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


def scoring_active():

    r=subprocess.run(
        [
            "/usr/bin/systemctl",
            "is-active",
            "--quiet",
            "meteorradio-score-new.service",
        ],
        check=False,
        timeout=5,
    )

    return (
        r.returncode
        ==
        0
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

        except Exception as exc:

            print(
                "CACHE_DELETE_ERROR",
                name,
                repr(exc),
                flush=True
            )

    return count


def append_ledger(record):

    LEDGER.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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


def main():

    now=time.time()

    if (
        not INIT_ONLY
        and
        scoring_active()
    ):

        print(
            "SKIP scoring active",
            flush=True
        )

        return 0


    CACHE.mkdir(
        parents=True,
        exist_ok=True
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
                {
                    "scores":{}
                }
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


            #
            # Wszystkie istniejące, ocenione SMP 1–7.
            #
            present={}

            for name,raw in scores.items():

                score=score_value(
                    raw
                )

                if score not in POLICY_DAYS:
                    continue

                p=RADAR/name

                if not p.is_file():
                    continue

                present[name]={
                    "score":score,
                    "path":p,
                }


            #
            # Usuń stan trackingowy plików,
            # których już fizycznie/indexowo nie ma.
            #
            for name in list(
                qualified.keys()
            ):

                if name not in present:

                    qualified.pop(
                        name,
                        None
                    )


            new_tracked=0


            #
            # Zachowujemy istniejący qualified_at dla obecnych 5–7.
            # Nowe 1–7 dostają timestamp przy pierwszym zobaczeniu
            # przez retencję.
            #
            for name in present:

                if name not in qualified:

                    qualified[name]=now
                    new_tracked+=1


            deleted=0
            deleted_cache=0
            freed=0
            index_changed=False

            deleted_by_score={
                n:0
                for n in range(1,8)
            }


            if not INIT_ONLY:

                for name in list(
                    qualified.keys()
                ):

                    row=present.get(
                        name
                    )

                    if row is None:
                        continue

                    score=row["score"]
                    p=row["path"]


                    #
                    # ❤️ = bezterminowo.
                    #
                    if name in likes:
                        continue


                    try:

                        qualified_at=float(
                            qualified[name]
                        )

                    except Exception:

                        qualified_at=now
                        qualified[name]=now


                    ttl=POLICY_SECONDS[
                        score
                    ]

                    age=(
                        now
                        -
                        qualified_at
                    )


                    if age < ttl:
                        continue


                    try:

                        size=(
                            p.stat().st_size
                            if p.exists()
                            else 0
                        )

                    except Exception:

                        size=0


                    try:

                        if p.exists():
                            p.unlink()

                    except Exception as exc:

                        print(
                            "DELETE_ERROR",
                            name,
                            repr(exc),
                            flush=True
                        )

                        continue


                    cache_count=delete_cache(
                        name
                    )


                    scores.pop(
                        name,
                        None
                    )

                    qualified.pop(
                        name,
                        None
                    )

                    #
                    # Dla pewności — wpis like nie powinien tu
                    # istnieć, bo liked records są pomijane.
                    #
                    likes.pop(
                        name,
                        None
                    )


                    deleted+=1
                    deleted_cache+=cache_count
                    freed+=size
                    deleted_by_score[
                        score
                    ]+=1

                    index_changed=True


                    append_ledger(
                        {
                            "time":now,
                            "file":name,
                            "score":score,
                            "qualified_at":
                                qualified_at,
                            "age_seconds":age,
                            "ttl_days":
                                POLICY_DAYS[
                                    score
                                ],
                            "bytes":size,
                            "cache_deleted":
                                cache_count,
                            "liked":False,
                            "reason":
                                f"not_liked_after_{POLICY_DAYS[score]}_days",
                            "source":
                                "retention_score_ttl_1_7",
                        }
                    )


                    print(
                        "DELETE_EXPIRED",
                        name,
                        f"score={score}",
                        f"ttl_days={POLICY_DAYS[score]}",
                        f"bytes={size}",
                        f"cache={cache_count}",
                        flush=True
                    )


            #
            # Stan retencji V2.
            #
            state_data={
                "version":2,
                "policy_days":{
                    str(k):v
                    for k,v
                    in POLICY_DAYS.items()
                },
                "updated":now,
                "qualified_at":
                    qualified,
            }


            likes_data["likes"]=likes
            likes_data["updated"]=now


            if index_changed:

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


            liked_tracked=sum(
                1
                for name
                in present
                if name in likes
            )


            print(
                "INIT_ONLY=",
                INIT_ONLY
            )

            print(
                "TRACKED=",
                len(qualified)
            )

            print(
                "NEW_TRACKED=",
                new_tracked
            )

            print(
                "LIKED=",
                liked_tracked
            )

            print(
                "DELETED=",
                deleted
            )

            print(
                "DELETED_CACHE=",
                deleted_cache
            )

            print(
                "FREED_MIB=",
                round(
                    freed
                    /
                    1024
                    /
                    1024,
                    2
                )
            )

            print(
                "POLICY_DAYS=",
                POLICY_DAYS
            )

            for score in range(
                1,
                8
            ):

                print(
                    f"DELETED_SCORE_{score}=",
                    deleted_by_score[
                        score
                    ]
                )


        finally:

            fcntl.flock(
                lock_f.fileno(),
                fcntl.LOCK_UN
            )


    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
