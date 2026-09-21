#!/usr/bin/env python3

# MR_STATS_8097_V1

import json
import re
import time
import urllib.request

from collections import Counter
from datetime import datetime, timedelta
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from urllib.parse import urlparse


HOST = "0.0.0.0"
PORT = 8097

RADAR = Path(
    "/home/pi/radar_data"
)

CACHE = Path(
    "/home/pi/meteorradio-web/cache"
)

HEALTH_LATEST = Path(
    "/home/pi/meteorradio-web/health/latest.json"
)

HEALTH_HISTORY = Path(
    "/home/pi/meteorradio-web/health/history.jsonl"
)

SCORE_INDEX = CACHE / "v562_score_index.json"

LOW_LEDGER = (
    CACHE /
    "v562_deleted_low_scores.jsonl"
)

RETENTION_LEDGER = (
    CACHE /
    "v562_retention_deleted.jsonl"
)


SMP_RE = re.compile(
    r"^SMP_\d+_"
    r"(\d{8})_"
    r"(\d{6})_"
    r"\d+\.npz$"
)


def read_json(path, default=None):

    if default is None:
        default = {}

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return default


def read_jsonl(path):

    rows = []

    try:
        with path.open(
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                try:
                    x = json.loads(line)
                except Exception:
                    continue

                if isinstance(x, dict):
                    rows.append(x)

    except Exception:
        pass

    return rows


def filename_dt(name):

    if not isinstance(name, str):
        return None

    name = Path(name).name

    m = SMP_RE.match(name)

    if not m:
        return None

    try:

        naive = datetime.strptime(
            m.group(1)
            +
            m.group(2),
            "%Y%m%d%H%M%S"
        )

        tz = (
            datetime.now()
            .astimezone()
            .tzinfo
        )

        return naive.replace(
            tzinfo=tz
        )

    except Exception:
        return None


def collect_event_names():

    names = set()

    #
    # Aktualne SMP.
    #
    try:

        for p in RADAR.rglob(
            "SMP_*.npz"
        ):
            names.add(
                p.name
            )

    except Exception:
        pass


    #
    # Wszystkie JSONL w cache.
    #
    # Dzięki temu wykresy zachowują także
    # wpisy detekcji, których SMP został
    # później usunięty przez score 1-4
    # albo retencję.
    #
    try:

        for ledger in CACHE.glob(
            "*.jsonl"
        ):

            for row in read_jsonl(
                ledger
            ):

                for key in (
                    "file",
                    "filename",
                    "npz",
                ):

                    value = row.get(
                        key
                    )

                    if (
                        isinstance(
                            value,
                            str
                        )
                        and
                        SMP_RE.match(
                            Path(value).name
                        )
                    ):
                        names.add(
                            Path(value).name
                        )

    except Exception:
        pass


    rows = []

    for name in names:

        dt = filename_dt(name)

        if dt is not None:

            rows.append(
                (
                    name,
                    dt,
                )
            )

    rows.sort(
        key=lambda x: x[1]
    )

    return rows


def make_interval_bins(
    events,
    hours,
    bin_minutes,
):

    now = (
        datetime.now()
        .astimezone()
    )

    start = (
        now
        -
        timedelta(
            hours=hours
        )
    )

    seconds = (
        bin_minutes
        *
        60
    )

    n = int(
        hours
        *
        60
        /
        bin_minutes
    )

    counts = [
        0
        for _ in range(n)
    ]

    for _, dt in events:

        delta = (
            dt
            -
            start
        ).total_seconds()

        if (
            delta < 0
            or
            delta >= hours * 3600
        ):
            continue

        idx = int(
            delta // seconds
        )

        if 0 <= idx < n:
            counts[idx] += 1


    out = []

    for i, count in enumerate(
        counts
    ):

        t = (
            start
            +
            timedelta(
                minutes=
                i * bin_minutes
            )
        )

        out.append(
            {
                "label":
                    t.strftime(
                        "%H:%M"
                    ),

                "value":
                    count,
            }
        )

    return out


def make_day_bins(
    events,
    days,
):

    now = (
        datetime.now()
        .astimezone()
    )

    today = now.date()

    first = (
        today
        -
        timedelta(
            days=days - 1
        )
    )

    counter = Counter()

    for _, dt in events:

        d = dt.date()

        if first <= d <= today:
            counter[d] += 1


    out = []

    for i in range(days):

        d = (
            first
            +
            timedelta(
                days=i
            )
        )

        out.append(
            {
                "label":
                    d.strftime(
                        "%d.%m"
                    ),

                "value":
                    counter.get(
                        d,
                        0
                    ),
            }
        )

    return out


def count_since(
    events,
    delta,
):

    now = (
        datetime.now()
        .astimezone()
    )

    start = (
        now
        -
        delta
    )

    return sum(
        1
        for _, dt in events
        if dt >= start
    )


def score_value(value):

    if isinstance(
        value,
        bool
    ):
        return None

    if isinstance(
        value,
        (int, float)
    ):
        return int(value)

    if isinstance(
        value,
        dict
    ):

        for key in (
            "score",
            "value",
            "rating",
        ):

            v = value.get(
                key
            )

            try:
                return int(v)
            except Exception:
                pass

    return None



# MR_STATS_SCORE_1_7_HISTORY_V1
# MR_STATS_SCORE_1_7_ROLLING24_V2

def make_score_history_24h(
    low_rows,
    retention_rows,
    score_index,
):

    now = (
        datetime.now()
        .astimezone()
    )

    window_start = (
        now
        -
        timedelta(
            hours=24
        )
    )

    #
    # 24 prawdziwe przedziały po 60 minut,
    # przesuwane razem z chwilą "teraz".
    #
    rows = []

    for i in range(24):

        start = (
            window_start
            +
            timedelta(
                hours=i
            )
        )

        rows.append(
            {
                "start": start,

                "label":
                    start.strftime(
                        "%H:%M"
                    ),

                "scores": {
                    str(n): 0
                    for n in range(
                        1,
                        8
                    )
                },
            }
        )


    #
    # Jeden plik = jedna detekcja.
    #
    # ledger:
    #   historia usuniętych 1–4
    #
    # score-index:
    #   bieżące wpisy 1–7
    #
    # Jeżeli ten sam plik pojawi się w obu,
    # słownik events gwarantuje jedno liczenie.
    #
    events = {}


    def add_event(
        name,
        dt,
        score,
    ):

        if (
            dt is None
            or
            score not in range(
                1,
                8
            )
        ):
            return

        if (
            dt < window_start
            or
            dt > now
        ):
            return

        key = str(name).rsplit(
            "/",
            1
        )[-1]

        events[key] = (
            dt,
            score,
        )


    #
    # 1–4 zapisane w ledgerze.
    #
    for row in low_rows:

        try:
            score = int(
                row.get(
                    "score"
                )
            )
        except Exception:
            continue

        if score not in (
            1,
            2,
            3,
            4,
        ):
            continue

        name = row.get(
            "file"
        )

        dt = filename_dt(
            name
        )

        add_event(
            name,
            dt,
            score,
        )


    #
    # MR_STATS_RETENTION_LEDGER_1_7_V3
    #
    # Ręczne DELETE oraz automatyczna retencja score 1–7.
    #
    # add_event() zapisuje po nazwie pliku do słownika events,
    # więc ten sam SMP nie może zostać policzony podwójnie.
    #
    for row in retention_rows:

        try:
            score = int(
                row.get(
                    "score"
                )
            )
        except Exception:
            continue

        if score not in range(
            1,
            8
        ):
            continue

        name = row.get(
            "file"
        )

        dt = filename_dt(
            name
        )

        add_event(
            name,
            dt,
            score,
        )


    #
    # Score-index może chwilowo zawierać
    # także 1–4, dlatego NIE ograniczamy
    # już go wyłącznie do 5–7.
    #
    scores = (
        score_index.get(
            "scores",
            score_index,
        )
        if isinstance(
            score_index,
            dict,
        )
        else {}
    )

    if isinstance(
        scores,
        dict,
    ):

        for name, value in (
            scores.items()
        ):

            score = score_value(
                value
            )

            if score not in range(
                1,
                8
            ):
                continue

            dt = filename_dt(
                name
            )

            add_event(
                name,
                dt,
                score,
            )


    #
    # Rozdzielamy dokładnie te same
    # events na 24 × 60 min.
    #
    for name, (
        dt,
        score,
    ) in events.items():

        seconds = (
            dt
            -
            window_start
        ).total_seconds()

        idx = int(
            seconds
            //
            3600
        )

        #
        # Zdarzenie dokładnie na granicy
        # "now" może dać indeks 24.
        #
        if idx == 24:
            idx = 23

        if not (
            0 <= idx < 24
        ):
            continue

        rows[
            idx
        ][
            "scores"
        ][
            str(score)
        ] += 1


    return [
        {
            "label":
                row["label"],

            "scores":
                row["scores"],

            "total":
                sum(
                    row[
                        "scores"
                    ].values()
                ),
        }
        for row in rows
    ]


def health_summary():

    latest = read_json(
        HEALTH_LATEST,
        {}
    )

    history = read_jsonl(
        HEALTH_HISTORY
    )

    now_epoch = time.time()

    recent = []

    for row in history:

        try:

            epoch = float(
                row.get(
                    "epoch",
                    0
                )
            )

        except Exception:
            continue

        if (
            now_epoch
            -
            epoch
            <=
            86400
        ):
            recent.append(
                row
            )


    temps = []

    loads = []

    frees = []


    for row in recent:

        sys = row.get(
            "system",
            {}
        )

        for target, key in (
            (
                temps,
                "temperature_c",
            ),
            (
                loads,
                "load1",
            ),
            (
                frees,
                "disk_free_gib",
            ),
        ):

            try:
                target.append(
                    float(
                        sys.get(
                            key
                        )
                    )
                )
            except Exception:
                pass


    return {
        "latest":
            latest,

        "samples24":
            len(recent),

        "temp_max24":
            max(temps)
            if temps
            else None,

        "load_max24":
            max(loads)
            if loads
            else None,

        "disk_min24":
            min(frees)
            if frees
            else None,
    }


def queue_status():

    try:

        req = urllib.request.Request(
            "http://127.0.0.1:8095/status",
            headers={
                "User-Agent":
                    "MeteorRadio-Stats/1.0"
            },
        )

        with urllib.request.urlopen(
            req,
            timeout=3,
        ) as response:

            return json.loads(
                response.read()
                .decode(
                    "utf-8",
                    errors="replace"
                )
            )

    except Exception:
        return {}


def collect():

    now = (
        datetime.now()
        .astimezone()
    )

    events = collect_event_names()

    count1h = count_since(
        events,
        timedelta(
            hours=1
        ),
    )

    count24 = count_since(
        events,
        timedelta(
            hours=24
        ),
    )

    count7 = count_since(
        events,
        timedelta(
            days=7
        ),
    )

    count30 = count_since(
        events,
        timedelta(
            days=30
        ),
    )


    today = sum(
        1
        for _, dt in events
        if dt.date()
        ==
        now.date()
    )


    #
    # Score 1-4 usunięte w ostatnich 24 h.
    #
    low24 = 0

    low_scores = Counter()

    limit24 = (
        now
        -
        timedelta(
            hours=24
        )
    )

    for row in read_jsonl(
        LOW_LEDGER
    ):

        name = row.get(
            "file"
        )

        dt = filename_dt(
            name
        )

        if (
            dt is None
            or
            dt < limit24
        ):
            continue

        try:
            score = int(
                row.get(
                    "score"
                )
            )
        except Exception:
            score = None

        if score in (
            1,
            2,
            3,
            4,
        ):

            low24 += 1
            low_scores[
                str(score)
            ] += 1


    #
    # Aktualnie zachowane score 5-7.
    #
    index = read_json(
        SCORE_INDEX,
        {}
    )

    scores = index.get(
        "scores",
        index
    )

    kept24 = 0

    kept_total = 0

    score_dist = Counter()

    if isinstance(
        scores,
        dict
    ):

        for name, value in (
            scores.items()
        ):

            score = score_value(
                value
            )

            if score not in (
                5,
                6,
                7,
            ):
                continue

            kept_total += 1

            score_dist[
                str(score)
            ] += 1

            dt = filename_dt(
                name
            )

            if (
                dt is not None
                and
                dt >= limit24
            ):
                kept24 += 1


    #
    # MR_STATS_CURRENT_1_7_V3
    #
    # Finalna polityka retencji obejmuje score 1–7,
    # dlatego bieżący stan panelu nie może być liczony
    # wyłącznie dla 5–7.
    #
    current24 = 0

    current_total = 0

    current_score_dist = Counter()

    if isinstance(
        scores,
        dict
    ):

        for name, value in (
            scores.items()
        ):

            score = score_value(
                value
            )

            if score not in range(
                1,
                8
            ):
                continue

            current_total += 1

            current_score_dist[
                str(score)
            ] += 1

            dt = filename_dt(
                name
            )

            if (
                dt is not None
                and
                dt >= limit24
            ):
                current24 += 1


    #
    # Retencja — ile faktycznie
    # skasowano w ostatnich 24 h.
    #
    retention24 = 0

    now_epoch = time.time()

    for row in read_jsonl(
        RETENTION_LEDGER
    ):

        try:

            epoch = float(
                row.get(
                    "time",
                    row.get(
                        "deleted_at",
                        0
                    )
                )
            )

        except Exception:
            continue

        if (
            now_epoch
            -
            epoch
            <=
            86400
        ):
            retention24 += 1


    #
    # MR_STATS_SCORE_1_7_HISTORY_V1
    #
    # Rozkład 1–7 i historia godzinowa.
    #
    low_rows_all = read_jsonl(
        LOW_LEDGER
    )

    retention_rows_all = read_jsonl(
        RETENTION_LEDGER
    )

    score_index_all = read_json(
        SCORE_INDEX,
        {}
    )

    score_history_24h = (
        make_score_history_24h(
            low_rows_all,
            retention_rows_all,
            score_index_all,
        )
    )

    score_24h = {
        str(n): 0
        for n in range(
            1,
            8
        )
    }

    for row in score_history_24h:

        for score, count in (
            row.get(
                "scores",
                {}
            ).items()
        ):

            try:
                score_24h[
                    str(score)
                ] += int(
                    count
                )
            except Exception:
                pass

    scored_24h_total = sum(
        score_24h.values()
    )

    health = health_summary()

    latest = health.get(
        "latest",
        {}
    )

    sys = latest.get(
        "system",
        {}
    )

    likes = latest.get(
        "likes",
        {}
    )

    #
    # MR_STATS_LIKES_LIVE_V4
    #
    # Licznik serduszek musi być bieżący.
    # Health snapshot odświeża się tylko okresowo,
    # dlatego dla samego licznika ❤️ czytamy
    # kanoniczny v562_likes.json.
    #
    # Jeśli plik jest chwilowo niedostępny lub
    # ma niepoprawny schemat, zostawiamy bezpieczny
    # fallback do ostatniego health snapshotu.
    #
    live_liked = likes.get(
        "liked"
    )

    likes_state_path = (
        CACHE
        /
        "v562_likes.json"
    )

    if likes_state_path.is_file():

        live_likes_state = read_json(
            likes_state_path,
            {}
        )

        if isinstance(
            live_likes_state,
            dict
        ):

            live_likes_map = (
                live_likes_state.get(
                    "likes"
                )
            )

            if isinstance(
                live_likes_map,
                dict
            ):

                live_liked = len(
                    live_likes_map
                )

    queue = queue_status()


    return {
        "ok": True,

        "generated":
            now.isoformat(),

        "summary": {

            "last1h":
                count1h,

            "last24h":
                count24,

            "last7d":
                count7,

            "last30d":
                count30,

            "today":
                today,

            "avg24":
                round(
                    count24 / 24,
                    2
                ),

            "deleted_low24":
                low24,

            "kept_5_7_24":
                kept24,

            "kept_5_7_total":
                kept_total,

            # MR_STATS_TILES_CURRENT_LOGIC_V5
            #
            # Pełna liczba ocen 1–7 z ostatnich 24 h:
            # bieżący score-index + historia plików już usuniętych.
            #
            "scored_1_7_24":
                scored_24h_total,

            "current_1_7_24":
                current24,

            "current_1_7_total":
                current_total,

            "retention_deleted24":
                retention24,

            "score_remaining":
                queue.get(
                    "remaining"
                ),

            "score_state":
                queue.get(
                    "state"
                ),

            "liked":
                live_liked,

            "health_status":
                latest.get(
                    "status"
                ),

            "temperature":
                sys.get(
                    "temperature_c"
                ),

            "load1":
                sys.get(
                    "load1"
                ),

            "disk_free":
                sys.get(
                    "disk_free_gib"
                ),

            "temp_max24":
                health.get(
                    "temp_max24"
                ),

            "load_max24":
                health.get(
                    "load_max24"
                ),

            "disk_min24":
                health.get(
                    "disk_min24"
                ),

            "health_samples24":
                health.get(
                    "samples24"
                ),
        },

        "scores": {
            "low24":
                dict(
                    low_scores
                ),

            "kept":
                dict(
                    score_dist
                ),

            "current":
                dict(
                    current_score_dist
                ),

            # MR_STATS_SCORE_1_7_HISTORY_V1
            "last24":
                score_24h,

            "last24_total":
                scored_24h_total,

            "hourly24":
                score_history_24h,
        },

        "charts": {

            "hour":
                make_interval_bins(
                    events,
                    1,
                    5,
                ),

            "day":
                make_interval_bins(
                    events,
                    24,
                    60,
                ),

            "week":
                make_day_bins(
                    events,
                    7,
                ),

            "month":
                make_day_bins(
                    events,
                    30,
                ),
        },
    }


HTML = r'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>MeteorRadio — statystyki</title>

<style>
:root{
    color-scheme:dark;
    --bg:#08111a;
    --panel:#111e29;
    --panel2:#0d1822;
    --line:#2a4254;
    --text:#eef6ff;
    --muted:#8fa6b8;
    --cyan:#59b8d7;
    --green:#45c287;
}

*{
    box-sizing:border-box;
}

body{
    margin:0;
    background:var(--bg);
    color:var(--text);
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.wrap{
    width:min(1280px,96vw);
    margin:24px auto 50px;
}

.header{
    display:flex;
    gap:16px;
    align-items:center;
    justify-content:space-between;
    margin-bottom:16px;
}

h1{
    margin:0;
    font-size:22px;
}

.sub{
    margin-top:5px;
    color:var(--muted);
    font-size:13px;
}

.actions{
    display:flex;
    gap:8px;
}

button,
a.btn{
    border:1px solid var(--line);
    background:#182b3a;
    color:#fff;
    border-radius:7px;
    padding:8px 12px;
    text-decoration:none;
    cursor:pointer;
    font-weight:700;
    font-size:12px;
}

.panel{
    background:var(--panel);
    border:1px solid var(--line);
    border-radius:10px;
    margin-bottom:14px;
    overflow:hidden;
}

.panelHead{
    padding:13px 15px;
    border-bottom:1px solid var(--line);
    display:flex;
    justify-content:space-between;
    align-items:center;
}

.panelTitle{
    font-size:13px;
    font-weight:800;
    text-transform:uppercase;
}

.panelMeta{
    color:var(--muted);
    font-size:11px;
}

.report{
    padding:14px;
}

.cards{
    display:grid;
    grid-template-columns:
        repeat(
            4,
            minmax(0,1fr)
        );
    gap:10px;
}

.card{
    border:1px solid #273f50;
    background:var(--panel2);
    border-radius:9px;
    padding:11px 12px;
    min-height:82px;
}

.cardLabel{
    color:var(--muted);
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.04em;
    margin-bottom:7px;
}

.cardValue{
    font-size:20px;
    font-weight:850;
    line-height:1;
}

.cardMeta{
    color:var(--muted);
    font-size:11px;
    margin-top:7px;
}

.ok{
    color:var(--green);
}

.warn{
    color:#ffd166;
}

.crit{
    color:#ff7979;
}


/* MR_STATS_SCORE_1_7_HISTORY_V1 */

.scoreCards{
    display:grid;
    grid-template-columns:
        repeat(
            7,
            minmax(
                0,
                1fr
            )
        );
    gap:8px;
    padding:14px;
}

.scoreCard{
    border:1px solid #273f50;
    background:var(--panel2);
    border-radius:9px;
    overflow:hidden;
}

.scoreCardTop{
    height:5px;
}

.scoreCardBody{
    padding:10px 10px 11px;
    text-align:center;
}

.scoreCardLabel{
    font-size:10px;
    color:var(--muted);
    text-transform:uppercase;
    letter-spacing:.05em;
    margin-bottom:6px;
}

.scoreCardValue{
    font-size:22px;
    font-weight:850;
    line-height:1;
}

.scoreCardMeta{
    margin-top:7px;
    font-size:10px;
    color:var(--muted);
}

.scoreLegend{
    display:flex;
    flex-wrap:wrap;
    gap:8px 14px;
    padding:
        10px
        14px
        0;
    color:var(--muted);
    font-size:11px;
}

.scoreLegendItem{
    display:flex;
    align-items:center;
    gap:5px;
}

.scoreDot{
    width:9px;
    height:9px;
    border-radius:2px;
}

.scoreHistoryScroll{
    overflow-x:auto;
    padding:
        14px
        12px
        8px;
}

.scoreHistory{
    min-width:1100px;
    height:245px;
    display:flex;
    gap:7px;
    align-items:flex-end;
    padding:
        34px
        6px
        28px;
}

.scoreHour{
    flex:1;
    min-width:31px;
    height:178px;
    position:relative;
}

.scoreStackArea{
    position:absolute;
    top:0;
    left:0;
    right:0;
    bottom:24px;
}

.scoreStack{
    position:absolute;
    left:15%;
    right:15%;
    bottom:0;
    height:var(--h);
    min-height:0;
    display:flex;
    flex-direction:column-reverse;
    border-radius:3px 3px 0 0;
    overflow:hidden;
}

.scoreSegment{
    width:100%;
    height:var(--seg);
    min-height:0;
}

.scoreHourValue{
    position:absolute;
    left:50%;
    bottom:
        calc(
            var(--h)
            +
            6px
        );
    transform:
        translateX(-50%);
    font-size:10px;
    font-weight:800;
    white-space:nowrap;
    color:#eef8ff;
}

.scoreHourLabel{
    position:absolute;
    left:50%;
    bottom:0;
    transform:
        translateX(-50%);
    font-size:9px;
    color:var(--muted);
    white-space:nowrap;
}

.scoreHour.zero
.scoreHourValue{
    display:none;
}

/*
 * Stała paleta ocen.
 * Niskie = cieplejsze,
 * wysokie = chłodniejsze/zielone.
 */
.score1{ background:#8d4650; }
.score2{ background:#a86749; }
.score3{ background:#b88c45; }
.score4{ background:#a9a34c; }
.score5{ background:#629e63; }
.score6{ background:#478f85; }
.score7{ background:#4f7fb0; }

@media(max-width:1050px){
    .scoreCards{
        grid-template-columns:
            repeat(
                4,
                minmax(0,1fr)
            );
    }
}

@media(max-width:650px){
    .scoreCards{
        grid-template-columns:
            repeat(
                2,
                minmax(0,1fr)
            );
    }
}

.chartScroll{
    overflow-x:auto;
    padding:12px 10px 8px;
}

.chart{
    min-width:760px;
    height:225px;
    display:flex;
    gap:7px;
    align-items:flex-end;
    padding:
        32px
        8px
        25px;
    border-top:1px solid rgba(255,255,255,.025);
}

.chart.month{
    min-width:1050px;
    gap:4px;
}

.col{
    flex:1;
    height:168px;
    position:relative;
    min-width:16px;
}

.barArea{
    position:absolute;
    left:0;
    right:0;
    top:0;
    bottom:22px;
}

.bar{
    position:absolute;
    left:12%;
    right:12%;
    bottom:0;
    height:var(--h);
    min-height:0;
    background:var(--cyan);
    border-radius:2px 2px 0 0;
}

.bar.nonzero{
    min-height:3px;
}

.value{
    position:absolute;
    left:50%;
    bottom:
        calc(
            var(--h)
            +
            7px
        );
    transform:translateX(-50%);
    font-size:10px;
    font-weight:800;
    line-height:1;
    color:#dff8ff;
    white-space:nowrap;
}

.label{
    position:absolute;
    left:50%;
    bottom:0;
    transform:translateX(-50%);
    font-size:9px;
    color:var(--muted);
    white-space:nowrap;
}

.zero .value{
    display:none;
}

.footer{
    color:var(--muted);
    font-size:11px;
    text-align:right;
    padding-top:4px;
}

@media(max-width:900px){
    .cards{
        grid-template-columns:
            repeat(
                2,
                minmax(0,1fr)
            );
    }
}

@media(max-width:560px){
    .cards{
        grid-template-columns:1fr;
    }

    .header{
        align-items:flex-start;
        flex-direction:column;
    }
}
</style>
</head>

<body>

<div class="wrap">

    <div class="header">

        <div>
            <h1>☄ MeteorRadio — statystyki</h1>
            <div class="sub">
                GRAVES 143.050 MHz · osobny panel 8097
            </div>
        </div>

        <div class="actions">

            <a
                class="btn"
                href="#" onclick="location.href='http://'+location.hostname+':8094/';return false;"
            >
                MeteorRadio
            </a>

            <a
                class="btn"
                href="#" onclick="location.href='http://'+location.hostname+':8096/';return false;"
            >
                Ulubione
            </a>

            <button id="refresh">
                ↻ Odśwież
            </button>

        </div>

    </div>


    <section class="panel">

        <div class="panelHead">
            <div class="panelTitle">
                Raport dobowy
            </div>

            <div
                class="panelMeta"
                id="generated"
            >
                —
            </div>
        </div>

        <div class="report">

            <div
                class="cards"
                id="cards"
            ></div>

        </div>

    </section>



    <!-- MR_STATS_SCORE_1_7_HISTORY_V1 -->

    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Rozkład ocen 1–7 — ostatnie 24 h
            </div>

            <div
                class="panelMeta"
                id="metaScores24"
            >
                —
            </div>

        </div>

        <div
            class="scoreCards"
            id="scoreCards24"
        ></div>

    </section>


    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Historia ocen 1–7 — ostatnie 24 h
            </div>

            <div
                class="panelMeta"
                id="metaScoreHistory"
            >
                1 godzina / kolumna
            </div>

        </div>

        <div
            class="scoreLegend"
            id="scoreLegend"
        ></div>

        <div class="scoreHistoryScroll">

            <div
                class="scoreHistory"
                id="scoreHistory24"
            ></div>

        </div>

    </section>


    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Ostatnia godzina
            </div>

            <div
                class="panelMeta"
                id="metaHour"
            ></div>

        </div>

        <div class="chartScroll">
            <div
                class="chart"
                id="chartHour"
            ></div>
        </div>

    </section>


    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Ostatnie 24 godziny
            </div>

            <div
                class="panelMeta"
                id="metaDay"
            ></div>

        </div>

        <div class="chartScroll">
            <div
                class="chart"
                id="chartDay"
            ></div>
        </div>

    </section>


    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Ostatnie 7 dni
            </div>

            <div
                class="panelMeta"
                id="metaWeek"
            ></div>

        </div>

        <div class="chartScroll">
            <div
                class="chart"
                id="chartWeek"
            ></div>
        </div>

    </section>


    <section class="panel">

        <div class="panelHead">

            <div class="panelTitle">
                Ostatnie 30 dni
            </div>

            <div
                class="panelMeta"
                id="metaMonth"
            ></div>

        </div>

        <div class="chartScroll">
            <div
                class="chart month"
                id="chartMonth"
            ></div>
        </div>

    </section>

    <div
        class="footer"
        id="footer"
    ></div>

</div>


<script>
function esc(v){
    return String(
        v ?? "—"
    )
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;");
}

function num(v,d=0){

    const n=Number(v);

    if(!Number.isFinite(n)){
        return "—";
    }

    return n.toLocaleString(
        "pl-PL",
        {
            minimumFractionDigits:d,
            maximumFractionDigits:d
        }
    );
}

function statusClass(v){

    v=String(
        v || ""
    ).toUpperCase();

    if(v==="OK") return "ok";
    if(v==="WARN") return "warn";
    if(v==="CRIT") return "crit";

    return "";
}


function card(
    label,
    value,
    meta="",
    cls=""
){
    return `
        <div class="card">

            <div class="cardLabel">
                ${esc(label)}
            </div>

            <div class="cardValue ${cls}">
                ${esc(value)}
            </div>

            <div class="cardMeta">
                ${esc(meta)}
            </div>

        </div>
    `;
}



// MR_STATS_SCORE_1_7_HISTORY_V1

function renderScoreDistribution(d){

    const host=
        document.getElementById(
            "scoreCards24"
        );

    if(!host) return;

    const scores=
        d?.scores?.last24
        ||
        {};

    const total=
        Number(
            d?.scores?.last24_total
        )
        ||
        0;

    const html=[];

    for(
        let score=1;
        score<=7;
        score++
    ){

        const count=
            Number(
                scores[
                    String(score)
                ]
            )
            ||
            0;

        const pct=
            total>0
            ?
            (
                count
                /
                total
                *
                100
            )
            :
            0;

        html.push(`
            <div class="scoreCard">

                <div
                    class="scoreCardTop score${score}"
                ></div>

                <div class="scoreCardBody">

                    <div class="scoreCardLabel">
                        Ocena ${score}
                    </div>

                    <div class="scoreCardValue">
                        ${count}
                    </div>

                    <div class="scoreCardMeta">
                        ${pct.toFixed(1)}%
                    </div>

                </div>

            </div>
        `);
    }

    host.innerHTML=
        html.join("");

    const meta=
        document.getElementById(
            "metaScores24"
        );

    if(meta){

        meta.textContent=
            total
            +
            " ocenionych detekcji";
    }
}


function renderScoreLegend(){

    const host=
        document.getElementById(
            "scoreLegend"
        );

    if(!host) return;

    host.innerHTML=
        Array.from(
            {
                length:7
            },
            (_,i)=>i+1
        )
        .map(
            score=>`
                <div class="scoreLegendItem">

                    <span
                        class="scoreDot score${score}"
                    ></span>

                    <span>
                        ocena ${score}
                    </span>

                </div>
            `
        )
        .join("");
}


function renderScoreHistory(d){

    const host=
        document.getElementById(
            "scoreHistory24"
        );

    if(!host) return;

    const rows=
        Array.isArray(
            d?.scores?.hourly24
        )
        ?
        d.scores.hourly24
        :
        [];

    const max=
        Math.max(
            1,
            ...rows.map(
                r=>
                    Number(
                        r.total
                    )
                    ||
                    0
            )
        );

    host.innerHTML=
        rows.map(
            row=>{

                const total=
                    Number(
                        row.total
                    )
                    ||
                    0;

                /*
                 * Maksymalny słupek = 80%.
                 * Nad nim zostaje osobne miejsce
                 * na wartość liczbową.
                 */
                const h=
                    total
                    ?
                    Math.max(
                        3,
                        total
                        /
                        max
                        *
                        80
                    )
                    :
                    0;

                let segments="";

                for(
                    let score=1;
                    score<=7;
                    score++
                ){

                    const count=
                        Number(
                            row.scores?.[
                                String(score)
                            ]
                        )
                        ||
                        0;

                    const seg=
                        total>0
                        ?
                        count
                        /
                        total
                        *
                        100
                        :
                        0;

                    if(count>0){

                        segments+=`
                            <div
                                class="
                                    scoreSegment
                                    score${score}
                                "
                                style="
                                    --seg:${seg}%
                                "
                                title="
                                    Ocena ${score}: ${count}
                                "
                            ></div>
                        `;
                    }
                }

                return `
                    <div
                        class="
                            scoreHour
                            ${
                                total
                                ?
                                ""
                                :
                                "zero"
                            }
                        "
                        style="
                            --h:${h}%
                        "
                    >

                        <div class="scoreStackArea">

                            <div class="scoreHourValue">
                                ${total}
                            </div>

                            <div class="scoreStack">
                                ${segments}
                            </div>

                        </div>

                        <div class="scoreHourLabel">
                            ${esc(row.label)}
                        </div>

                    </div>
                `;
            }
        )
        .join("");


    const meta=
        document.getElementById(
            "metaScoreHistory"
        );

    if(meta){

        meta.textContent=
            "1 godzina / kolumna · "
            +
            (
                Number(
                    d?.scores?.last24_total
                )
                ||
                0
            )
            +
            " ocen";
    }
}


function renderChart(
    id,
    rows
){

    const host=
        document.getElementById(
            id
        );

    if(!host) return;

    rows=
        Array.isArray(rows)
        ?
        rows
        :
        [];

    const values=
        rows.map(
            x=>
                Number(x.value)
                ||
                0
        );

    const max=
        Math.max(
            1,
            ...values
        );

    host.innerHTML=
        rows.map(
            row=>{

                const value=
                    Number(
                        row.value
                    )
                    ||
                    0;

                //
                // Maksymalny słupek zajmuje 78%.
                // Zostaje ponad nim stałe miejsce
                // dla wartości liczbowej.
                //
                const h=
                    value
                    ?
                    Math.max(
                        3,
                        (
                            value
                            /
                            max
                        )
                        *
                        78
                    )
                    :
                    0;

                return `
                    <div
                        class="col ${
                            value
                            ?
                            ""
                            :
                            "zero"
                        }"
                        style="--h:${h}%"
                    >

                        <div class="barArea">

                            <div class="value">
                                ${value}
                            </div>

                            <div
                                class="bar ${
                                    value
                                    ?
                                    "nonzero"
                                    :
                                    ""
                                }"
                            ></div>

                        </div>

                        <div class="label">
                            ${esc(row.label)}
                        </div>

                    </div>
                `;
            }
        )
        .join("");
}


async function refresh(){

    const button=
        document.getElementById(
            "refresh"
        );

    button.disabled=true;
    button.textContent="Odświeżam…";

    try{

        const r=
            await fetch(
                "/api/data?t="
                +
                Date.now(),
                {
                    cache:"no-store"
                }
            );

        const d=
            await r.json();

        if(!d.ok){
            throw new Error(
                "API not ok"
            );
        }

        const s=
            d.summary
            ||
            {};

        const health=
            s.health_status
            ||
            "—";

        const cards=[];

        cards.push(
            card(
                "Detekcje dziś",
                num(s.today),
                "wszystkie zarejestrowane"
            )
        );

        cards.push(
            card(
                "Ostatnie 24 h",
                num(
                    s.last24h
                ),
                "wszystkie zarejestrowane"
            )
        );

        cards.push(
            card(
                "Średnia / h",
                (
                    num(
                        s.avg24
                    )
                    +
                    " / h"
                ),
                "średnia z ostatnich 24 h"
            )
        );

        cards.push(
            card(
                "Ocenione 1–7 / 24 h",
                num(
                    s.scored_1_7_24
                ),
                "pełna historia ocen"
            )
        );

        cards.push(
            card(
                "Retencja / 24 h",
                num(
                    s.retention_deleted24
                ),
                "usunięte wg TTL 1–7"
            )
        );

        cards.push(
            card(
                "Polubione",
                num(
                    s.liked
                ),
                "chronione bezterminowo"
            )
        );

        cards.push(
            card(
                "Kolejka oceny",
                num(
                    s.score_remaining
                ),
                String(
                    s.score_state
                    ??
                    "—"
                )
            )
        );

        cards.push(
            card(
                "Health",
                health,
                "bieżący stan stacji",
                statusClass(
                    health
                )
            )
        );

        cards.push(
            card(
                "Temperatura",
                Number.isFinite(
                    Number(
                        s.temperature
                    )
                )
                ?
                num(
                    s.temperature,
                    1
                )
                +
                " °C"
                :
                "—",
                Number.isFinite(
                    Number(
                        s.temp_max24
                    )
                )
                ?
                "max 24 h: "
                +
                num(
                    s.temp_max24,
                    1
                )
                +
                " °C"
                :
                "max 24 h: brak danych"
            )
        );

        cards.push(
            card(
                "Load",
                Number.isFinite(
                    Number(
                        s.load1
                    )
                )
                ?
                num(
                    s.load1,
                    2
                )
                :
                "—",
                Number.isFinite(
                    Number(
                        s.load_max24
                    )
                )
                ?
                "max 24 h: "
                +
                num(
                    s.load_max24,
                    2
                )
                :
                "max 24 h: brak danych"
            )
        );

        cards.push(
            card(
                "Wolne miejsce",
                Number.isFinite(
                    Number(
                        s.disk_free
                    )
                )
                ?
                num(
                    s.disk_free,
                    2
                )
                +
                " GiB"
                :
                "—",
                Number.isFinite(
                    Number(
                        s.disk_min24
                    )
                )
                ?
                "minimum 24 h: "
                +
                num(
                    s.disk_min24,
                    2
                )
                +
                " GiB"
                :
                "minimum 24 h: brak danych"
            )
        );

        cards.push(
            card(
                "W score-index",
                num(
                    s.current_1_7_total
                ),
                "aktualnie przechowywane 1–7"
            )
        );


        document.getElementById(
            "cards"
        ).innerHTML=
            cards.join("");


        // MR_STATS_SCORE_1_7_HISTORY_V1
        renderScoreDistribution(
            d
        );

        renderScoreLegend();

        renderScoreHistory(
            d
        );

        renderChart(
            "chartHour",
            d.charts?.hour
        );

        renderChart(
            "chartDay",
            d.charts?.day
        );

        renderChart(
            "chartWeek",
            d.charts?.week
        );

        renderChart(
            "chartMonth",
            d.charts?.month
        );


        document.getElementById(
            "metaHour"
        ).textContent=
            num(s.last1h)
            +
            " detekcji · 5 min / słupek";


        document.getElementById(
            "metaDay"
        ).textContent=
            num(s.last24h)
            +
            " detekcji · 1 h / słupek";


        document.getElementById(
            "metaWeek"
        ).textContent=
            num(s.last7d)
            +
            " detekcji · 1 dzień / słupek";


        document.getElementById(
            "metaMonth"
        ).textContent=
            num(s.last30d)
            +
            " detekcji · 1 dzień / słupek";


        document.getElementById(
            "generated"
        ).textContent=
            new Date(
                d.generated
            ).toLocaleString(
                "pl-PL"
            );


        document.getElementById(
            "footer"
        ).textContent=
            "auto odświeżanie co 5 min · health próbek 24 h: "
            +
            num(
                s.health_samples24
            );

    }catch(e){

        document.getElementById(
            "cards"
        ).innerHTML=
            card(
                "Błąd",
                "Nie udało się pobrać danych",
                String(e),
                "crit"
            );

    }finally{

        button.disabled=false;
        button.textContent="↻ Odśwież";
    }
}


document.getElementById(
    "refresh"
).addEventListener(
    "click",
    refresh
);

refresh();

setInterval(
    ()=>{
        if(!document.hidden){
            refresh();
        }
    },
    5 * 60 * 1000
);
</script>


<!-- MR_STATS_HIDE_DUPLICATE_TILES_V1 -->
<script>
(function(){

    const duplicateLabels = new Set([
        "Średnia / h",
        "Temperatura",
        "Load",
        "Wolne miejsce"
    ]);


    function removeDuplicateTiles(){

        const candidates =
            document.querySelectorAll(
                "div, span"
            );

        for(const el of candidates){

            const text=(
                el.textContent || ""
            ).trim();

            if(!duplicateLabels.has(text)){
                continue;
            }


            /*
             * Etykieta kafla jest bezpośrednim
             * dzieckiem kontenera kafla.
             *
             * Nie opieramy się na nazwie klasy,
             * tylko na rzeczywistym tekście
             * czterech konkretnych etykiet.
             */

            let tile=el.parentElement;

            if(
                !tile
                ||
                tile === document.body
            ){
                continue;
            }


            /*
             * Dodatkowa ochrona:
             * kafel musi mieć więcej niż samo
             * pole etykiety.
             */

            if(
                tile.children.length < 2
                &&
                tile.parentElement
                &&
                tile.parentElement !== document.body
            ){
                tile=tile.parentElement;
            }


            if(
                tile
                &&
                tile !== document.body
            ){
                tile.remove();
            }
        }
    }


    let scheduled=false;

    function scheduleCleanup(){

        if(scheduled){
            return;
        }

        scheduled=true;

        requestAnimationFrame(
            ()=>{
                scheduled=false;
                removeDuplicateTiles();
            }
        );
    }


    if(
        document.readyState === "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            scheduleCleanup,
            {once:true}
        );

    }else{

        scheduleCleanup();
    }


    /*
     * 8097 odświeża zawartość dynamicznie,
     * dlatego pilnujemy również późniejszych
     * renderów raportu.
     */

    const observer=
        new MutationObserver(
            scheduleCleanup
        );

    observer.observe(
        document.documentElement,
        {
            childList:true,
            subtree:true
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

    server_version = (
        "MeteorRadioStats/1.0"
    )


    def log_message(
        self,
        fmt,
        *args
    ):
        pass


    def send_bytes(
        self,
        body,
        content_type,
        status=200,
    ):

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(
                len(body)
            )
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.end_headers()

        self.wfile.write(
            body
        )


    def send_json(
        self,
        payload,
        status=200,
    ):

        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )

        self.send_bytes(
            body,
            "application/json; charset=utf-8",
            status,
        )


    def do_GET(
        self
    ):

        path = urlparse(
            self.path
        ).path

        if path in (
            "/",
            "/index.html",
        ):

            self.send_bytes(
                HTML.encode(
                    "utf-8"
                ),
                "text/html; charset=utf-8",
            )

            return


        if path == "/api/data":

            try:

                self.send_json(
                    collect()
                )

            except Exception as e:

                self.send_json(
                    {
                        "ok": False,
                        "error": repr(e),
                    },
                    500,
                )

            return


        if path == "/healthz":

            self.send_json(
                {
                    "ok": True
                }
            )

            return


        self.send_json(
            {
                "ok": False,
                "error": "not found",
            },
            404,
        )


if __name__ == "__main__":

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT,
        ),
        Handler,
    )

    print(
        f"MeteorRadio stats listening on {PORT}",
        flush=True,
    )

    server.serve_forever()
