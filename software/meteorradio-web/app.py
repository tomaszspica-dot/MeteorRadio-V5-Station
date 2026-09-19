#!/usr/bin/env python3

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

from pathlib import Path
from urllib.parse import (
    urlparse,
    parse_qs,
)

import csv
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time


HOST = "0.0.0.0"
PORT = 8094

LIVE_FILE = Path(
    "/dev/shm/"
    "meteorradio-live/"
    "spectrum-fast.json"
)

RADAR_DATA = Path(
    "/home/pi/radar_data"
)

LOG_DIR = (
    RADAR_DATA
    / "Logs"
)

CACHE_DIR = Path(
    "/home/pi/"
    "meteorradio-web/"
    "cache"
)

RENDERER = Path(
    "/home/pi/"
    "meteorradio-web/"
    "render_detection.py"
)

VENVPY = Path(
    "/home/pi/"
    "vMeteorRadio/"
    "bin/python"
)

RENDER_LOCK = threading.Lock()

TARGET_FREQ_HZ = 143050000.0

# LISTENING_EXPOSURE_CACHE_V41
#
# Czas aktywnego meteorradio.service dzisiaj.
#
LISTENING_EXPOSURE_CACHE = {
    "checked": 0.0,
    "seconds": 0.0,
}




def command(
    args,
    timeout=3,
):

    try:

        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()

    except Exception:

        return ""


def human_uptime(
    seconds,
):

    seconds = int(
        max(
            0,
            seconds,
        )
    )

    days, rem = divmod(
        seconds,
        86400,
    )

    hours, rem = divmod(
        rem,
        3600,
    )

    minutes = rem // 60

    if days:

        return (
            f"{days} d "
            f"{hours} h "
            f"{minutes} min"
        )

    if hours:

        return (
            f"{hours} h "
            f"{minutes} min"
        )

    return (
        f"{minutes} min"
    )


def owner_data():

    raw = command(
        [
            "sudo",
            "-n",
            "/usr/local/sbin/"
            "radio-owner-control",
            "status",
        ],
        timeout=4,
    )

    try:

        return json.loads(
            raw
        )

    except Exception:

        return {}


def read_meminfo():

    result = {}

    try:

        for line in Path(
            "/proc/meminfo"
        ).read_text().splitlines():

            if ":" not in line:
                continue

            key, value = line.split(
                ":",
                1,
            )

            value = (
                value
                .strip()
                .split()[0]
            )

            result[key] = int(
                value
            )

    except Exception:

        pass

    return result


def meteor_pid():

    raw = command(
        [
            "systemctl",
            "show",
            "meteorradio.service",
            "-p",
            "MainPID",
            "--value",
        ]
    )

    try:

        return int(
            raw
        )

    except Exception:

        return 0


def process_rss_mb(
    pid,
):

    if not pid:
        return None

    path = Path(
        f"/proc/{pid}/status"
    )

    try:

        for line in path.read_text().splitlines():

            if line.startswith(
                "VmRSS:"
            ):

                kb = int(
                    line.split()[1]
                )

                return round(
                    kb / 1024.0,
                    1,
                )

    except Exception:

        pass

    return None






def get_throttle():

    raw = command(
        [
            "vcgencmd",
            "get_throttled",
        ]
    )

    m = re.search(
        r"0x([0-9a-fA-F]+)",
        raw,
    )

    if not m:

        return {
            "raw": "brak danych",
            "value": None,
            "state": "info",
        }

    value = int(
        m.group(1),
        16,
    )

    # V562_CURRENT_THROTTLE_ONLY
    #
    # vcgencmd:
    #
    # dolne bity 0..3 = stan AKTUALNY
    # górne bity      = zdarzenie historyczne
    #
    # Kafel HEALTH pokazuje wyłącznie stan aktualny.
    #
    current = (
        value
        &
        0xF
    )

    history = (
        value
        >>
        16
    ) & 0xF

    state = (
        "bad"
        if current
        else "ok"
    )

    return {
        "raw":
            f"0x{value:x}",

        "value":
            current,

        "history":
            history,

        "state":
            state,
    }


def parse_smp_time(
    name,
):

    m = re.match(
        r"^SMP_\d+_"
        r"(\d{8})_"
        r"(\d{6})_"
        r"(\d{6})\.npz$",
        name,
    )

    if not m:

        return None

    try:

        return datetime.datetime.strptime(
            "".join(
                m.groups()
            ),
            "%Y%m%d%H%M%S%f",
        )

    except Exception:

        return None


def csv_events():

    rows = []

    files = sorted(
        LOG_DIR.glob(
            "20??-??.csv"
        )
    )[-3:]

    for path in files:

        try:

            with path.open(
                newline="",
                encoding="utf-8",
                errors="replace",
            ) as fp:

                reader = csv.DictReader(
                    fp
                )

                for row in reader:

                    try:

                        dt = datetime.datetime.fromisoformat(
                            (
                                row.get(
                                    "date",
                                    ""
                                )
                                + "T"
                                + row.get(
                                    "time",
                                    ""
                                )
                            )
                        )

                    except Exception:

                        continue

                    def num(
                        key,
                    ):

                        try:
                            return float(
                                row.get(
                                    key,
                                    ""
                                )
                            )
                        except Exception:
                            return None

                    rows.append(
                        {
                            "dt": dt,
                            "snr_db":
                                num(
                                    "snratio"
                                ),

                            "duration_s":
                                num(
                                    "durations"
                                ),

                            "doppler_hz":
                                num(
                                    "doppler_estimate"
                                ),

                            "signal_db":
                                num(
                                    "signal"
                                ),

                            "noise_db":
                                num(
                                    "noise"
                                ),
                        }
                    )

        except Exception:

            continue

    rows.sort(
        key=lambda x: x["dt"]
    )

    return rows


def detection_data(
    limit=8,
    page=1,
):

    events = csv_events()

    today = (
        datetime.datetime.now()
        .date()
    )

    today_count = sum(
        1
        for x in events
        if x["dt"].date()
        == today
    )

    files = []

    try:

        files = list(
            RADAR_DATA.rglob(
                "SMP_*.npz"
            )
        )

    except Exception:

        pass

    entries = []

    for path in files:

        ftime = parse_smp_time(
            path.name
        )

        if ftime is None:
            continue

        candidate = None
        best_delta = None

        for event in events:

            delta = (
                event["dt"]
                - ftime
            ).total_seconds()

            #
            # MeteorRadio przechowuje także
            # kilka sekund sprzed triggera.
            #
            if (
                delta >= -1.0
                and
                delta <= 20.0
            ):

                if (
                    best_delta is None
                    or
                    abs(delta)
                    < best_delta
                ):

                    candidate = event
                    best_delta = abs(
                        delta
                    )

        dt = (
            candidate["dt"]
            if candidate
            else ftime
        )

        doppler = (
            candidate.get(
                "doppler_hz"
            )
            if candidate
            else None
        )

        freq_hz = (
            TARGET_FREQ_HZ
            + doppler
            if doppler is not None
            else None
        )

        try:

            size_mb = round(
                path.stat().st_size
                / 1024
                / 1024,
                2,
            )

        except Exception:

            size_mb = None

        entries.append(
            {
                "file": path.name,
                "time":
                    dt.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),

                "time_short":
                    dt.strftime(
                        "%H:%M:%S"
                    ),

                "snr_db":
                    (
                        round(
                            candidate[
                                "snr_db"
                            ],
                            2,
                        )
                        if (
                            candidate
                            and
                            candidate[
                                "snr_db"
                            ]
                            is not None
                        )
                        else None
                    ),

                "duration_s":
                    (
                        round(
                            candidate[
                                "duration_s"
                            ],
                            2,
                        )
                        if (
                            candidate
                            and
                            candidate[
                                "duration_s"
                            ]
                            is not None
                        )
                        else None
                    ),

                "doppler_hz":
                    (
                        round(
                            doppler,
                            1,
                        )
                        if doppler
                        is not None
                        else None
                    ),

                "frequency_hz":
                    (
                        round(
                            freq_hz,
                            1,
                        )
                        if freq_hz
                        is not None
                        else None
                    ),

                "size_mb":
                    size_mb,
            }
        )

    entries.sort(
        key=lambda x: x["time"],
        reverse=True,
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 8

    # MR_DETECTION_DATA_LIMIT_5000_V1
    limit = max(
        1,
        min(
            limit,
            5000,
        )
    )

    try:
        page = int(page)
    except Exception:
        page = 1

    page = max(
        1,
        page,
    )

    total_items = len(
        entries
    )

    total_pages = max(
        1,
        (
            total_items
            + limit
            - 1
        )
        // limit
    )

    if page > total_pages:
        page = total_pages

    start = (
        page
        - 1
    ) * limit

    end = (
        start
        + limit
    )

    return {
        "today_count":
            today_count,

        "total_items":
            total_items,

        "page":
            page,

        "total_pages":
            total_pages,

        "limit":
            limit,

        "detections":
            entries[
                start:end
            ],
    }



def meteor_listening_seconds_today():

    now = time.time()

    if (
        now
        - LISTENING_EXPOSURE_CACHE["checked"]
        < 30.0
    ):

        return LISTENING_EXPOSURE_CACHE[
            "seconds"
        ]


    local_now = datetime.datetime.now()

    midnight = local_now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    midnight_ts = midnight.timestamp()

    #
    # Bierzemy również dzień wcześniej,
    # żeby poprawnie obsłużyć sesję,
    # która przeszła przez północ.
    #
    since = (
        midnight
        - datetime.timedelta(
            days=1
        )
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    raw = command(
        [
            "journalctl",
            "-u",
            "meteorradio.service",
            "--since",
            since,
            "--no-pager",
            "-o",
            "json",
        ],
        timeout=6,
    )


    events = []


    for line in raw.splitlines():

        try:

            obj = json.loads(
                line
            )

            msg = str(
                obj.get(
                    "MESSAGE",
                    ""
                )
            )

            ts = (
                int(
                    obj[
                        "__REALTIME_TIMESTAMP"
                    ]
                )
                / 1_000_000.0
            )

        except Exception:

            continue


        #
        # systemd może dopisać opis jednostki
        # po nazwie service — dlatego używamy
        # "in", a nie pełnego porównania.
        #
        if (
            "Started meteorradio.service"
            in msg
        ):

            events.append(
                (
                    ts,
                    True,
                )
            )


        elif (
            "Stopping meteorradio.service"
            in msg
            or
            "Stopped meteorradio.service"
            in msg
            or
            "meteorradio.service: "
            "Deactivated successfully"
            in msg
            or
            "meteorradio.service: "
            "Failed with result"
            in msg
        ):

            events.append(
                (
                    ts,
                    False,
                )
            )


    events.sort(
        key=lambda x: x[0]
    )


    #
    # Stan dokładnie o północy.
    #
    active = False

    for ts,state in events:

        if ts < midnight_ts:
            active = state
        else:
            break


    total = 0.0
    cursor = midnight_ts


    for ts,state in events:

        if ts < midnight_ts:
            continue

        if ts > now:
            break


        if active and ts > cursor:

            total += (
                ts
                - cursor
            )


        active = state

        cursor = max(
            cursor,
            ts
        )


    currently_active = (
        command(
            [
                "systemctl",
                "is-active",
                "meteorradio.service",
            ]
        )
        == "active"
    )


    #
    # Otwarta bieżąca sesja.
    #
    if active and currently_active:

        if now > cursor:

            total += (
                now
                - cursor
            )


    #
    # Fallback, gdy journal nie ma wpisu
    # startowego bieżącej sesji.
    #
    elif currently_active and not active:

        try:

            mono_us = int(
                command(
                    [
                        "systemctl",
                        "show",
                        "meteorradio.service",
                        "-p",
                        "ActiveEnterTimestampMonotonic",
                        "--value",
                    ]
                )
            )


            uptime_s = float(
                Path(
                    "/proc/uptime"
                )
                .read_text()
                .split()[0]
            )


            boot_wall = (
                now
                - uptime_s
            )


            active_start = (
                boot_wall
                + mono_us
                / 1_000_000.0
            )


            active_start = max(
                active_start,
                midnight_ts
            )


            if now > active_start:

                total += (
                    now
                    - active_start
                )

        except Exception:

            pass


    total = max(
        0.0,
        total
    )


    LISTENING_EXPOSURE_CACHE[
        "checked"
    ] = now

    LISTENING_EXPOSURE_CACHE[
        "seconds"
    ] = total


    return total




# ============================================================
# V511_ADAPTIVE_REFRESH_CACHE
# ============================================================

V511_TTL_CACHE = {}


def _v511_cached(
    key,
    ttl,
    producer,
):

    now = time.monotonic()

    old = V511_TTL_CACHE.get(
        key
    )

    if (
        old is not None
        and
        now - old["time"] < ttl
    ):

        return old["value"]


    try:

        value = producer()

    except Exception:

        if old is not None:
            return old["value"]

        raise


    V511_TTL_CACHE[key] = {
        "time": now,
        "value": value,
    }

    return value


# ------------------------------------------------------------
# Zachowujemy oryginały
# ------------------------------------------------------------

_v511_owner_data_original = owner_data

_v511_read_meminfo_original = read_meminfo

_v511_meteor_pid_original = meteor_pid

_v511_process_rss_original = process_rss_mb

_v511_throttle_original = get_throttle

_v511_csv_events_original = csv_events

_v511_listening_original = (
    meteor_listening_seconds_today
)


# ------------------------------------------------------------
# OWNER
# 6 s
#
# Status NASŁUCH pozostaje dość szybki,
# ale nie odpalamy helpera przy każdym request.
# ------------------------------------------------------------

def owner_data():

    return (
        _v511_cached(
            "owner",
            6.0,
            _v511_owner_data_original,
        )
        or
        {}
    )


# ------------------------------------------------------------
# RAM
# 10 s
# ------------------------------------------------------------

def read_meminfo():

    return (
        _v511_cached(
            "meminfo",
            10.0,
            _v511_read_meminfo_original,
        )
        or
        {}
    )


# ------------------------------------------------------------
# PID MeteorRadio
# 15 s
# ------------------------------------------------------------

def meteor_pid():

    return (
        _v511_cached(
            "meteor_pid",
            15.0,
            _v511_meteor_pid_original,
        )
        or
        0
    )


# ------------------------------------------------------------
# RSS MeteorRadio
# 15 s
# ------------------------------------------------------------

def process_rss_mb(
    pid,
):

    return _v511_cached(
        "meteor_rss_"
        +
        str(pid),
        15.0,
        lambda:
            _v511_process_rss_original(
                pid
            ),
    )


# ------------------------------------------------------------
# THROTTLE
# 30 s
# ------------------------------------------------------------

def get_throttle():

    return _v511_cached(
        "throttle",
        30.0,
        _v511_throttle_original,
    )


# ------------------------------------------------------------
# CSV detekcji
# 5 s
#
# To bardzo ważne:
# wiele stron /api/detections w jednym refreshu
# dostanie tę samą sparsowaną listę.
# Nie czytamy tych samych CSV wielokrotnie.
# ------------------------------------------------------------

def csv_events():

    return (
        _v511_cached(
            "csv_events",
            5.0,
            _v511_csv_events_original,
        )
        or
        []
    )


# ------------------------------------------------------------
# STARA "STABILNOŚĆ"
#
# Kafel jest już usunięty z UI i frontend
# zamienia go na "Średnia detekcji / h".
#
# NIE MA WIĘC SENSU co kilka sekund wykonywać:
#
#   systemctl show NRestarts
#   journalctl -k --since -24 hours
#
# To był czysty koszt bez widocznego rezultatu.
# ------------------------------------------------------------

def detector_restarts():

    return 0


def usb_resets_24h():

    return None


# ------------------------------------------------------------
# CZAS NASŁUCHU
#
# Najdroższy fragment:
# pełne journalctl robimy:
#
#   - raz po starcie web
#   - po zmianie dnia
#   - po długiej przerwie w odpytywaniu (>120 s)
#
# Podczas normalnej pracy licznik jest zwiększany
# lokalnie bez ponownego skanowania journala.
# ------------------------------------------------------------

V511_LISTEN_STATE = {
    "ready": False,
    "date": None,
    "base": 0.0,
    "anchor": 0.0,
    "active": False,
    "last_call": 0.0,
}


def meteor_listening_seconds_today():

    now = time.time()

    today = (
        datetime.datetime
        .now()
        .date()
    )


    owner = owner_data()

    active_now = (
        owner.get(
            "meteorradio_running"
        )
        is True
    )


    st = V511_LISTEN_STATE


    previous_call = st[
        "last_call"
    ]

    st[
        "last_call"
    ] = now


    need_full_sync = (
        not st["ready"]

        or

        st["date"] != today

        or

        (
            previous_call > 0
            and
            now - previous_call > 120.0
        )
    )


    if need_full_sync:

        try:

            base = float(
                _v511_listening_original()
            )

        except Exception:

            base = (
                st["base"]
                if st["ready"]
                else 0.0
            )


        st.update(
            {
                "ready": True,
                "date": today,
                "base": max(
                    0.0,
                    base,
                ),
                "anchor": now,
                "active": active_now,
                "last_call": now,
            }
        )


        return st["base"]


    #
    # Jeżeli usługa zmieniła stan,
    # zamykamy / otwieramy lokalny odcinek.
    #
    if active_now != st["active"]:

        if st["active"]:

            st["base"] += max(
                0.0,
                now - st["anchor"],
            )


        st["anchor"] = now

        st["active"] = active_now


    value = st["base"]


    if st["active"]:

        value += max(
            0.0,
            now - st["anchor"],
        )


    return max(
        0.0,
        value,
    )


def health_data():

    cards = []

    #
    # Temperatura
    #
    temp = None

    try:

        temp = (
            float(
                Path(
                    "/sys/class/thermal/"
                    "thermal_zone0/temp"
                ).read_text().strip()
            )
            / 1000.0
        )

    except Exception:

        pass

    if temp is None:

        state = "info"
        value = "—"

    elif temp < 70:

        state = "ok"
        value = f"{temp:.1f} °C"

    elif temp < 80:

        state = "warn"
        value = f"{temp:.1f} °C"

    else:

        state = "bad"
        value = f"{temp:.1f} °C"

    cards.append(
        {
            "label":
                "CPU / SoC",

            "value":
                value,

            "detail":
                "temperatura Pi",

            "state":
                state,
        }
    )

    #
    # Throttling / power
    #
    throttle = get_throttle()

    cards.append(
        {
            "label":
                "Zasilanie / throttle",

            "value":
                (
                    "OK"
                    if throttle[
                        "value"
                    ] == 0
                    else throttle[
                        "raw"
                    ]
                ),

            "detail":
                (
                    "brak aktywnego throttlingu"
                    if throttle[
                        "value"
                    ] == 0
                    else
                    (
                        "aktywny problem · "
                        + throttle[
                            "raw"
                        ]
                    )
                ),

            "state":
                throttle[
                    "state"
                ],
        }
    )

    #
    # Load
    #
    try:

        load1, load5, load15 = os.getloadavg()

    except Exception:

        load1 = load5 = load15 = 0.0

    cores = max(
        1,
        os.cpu_count()
        or 1,
    )

    ratio = (
        load1
        / cores
    )

    if ratio < 0.75:
        state = "ok"
    elif ratio < 1.0:
        state = "warn"
    else:
        state = "bad"

    cards.append(
        {
            "label":
                "Load average",

            "value":
                f"{load1:.2f}",

            "detail":
                (
                    f"5m {load5:.2f} · "
                    f"15m {load15:.2f} · "
                    f"{cores} rdzenie"
                ),

            "state":
                state,
        }
    )

    #
    # RAM
    #
    mem = read_meminfo()

    total_kb = mem.get(
        "MemTotal",
        0,
    )

    avail_kb = mem.get(
        "MemAvailable",
        0,
    )

    if total_kb:

        free_pct = (
            100.0
            * avail_kb
            / total_kb
        )

        value = (
            f"{avail_kb/1024:.0f} MB"
        )

        detail = (
            f"{free_pct:.0f}% dostępne"
        )

        if free_pct > 20:
            state = "ok"
        elif free_pct > 10:
            state = "warn"
        else:
            state = "bad"

    else:

        value = "—"
        detail = "brak danych"
        state = "info"

    cards.append(
        {
            "label":
                "RAM wolny",

            "value":
                value,

            "detail":
                detail,

            "state":
                state,
        }
    )

    #
    # RSS MeteorRadio
    #
    pid = meteor_pid()
    rss = process_rss_mb(
        pid
    )

    cards.append(
        {
            "label":
                "MeteorRadio RSS",

            "value":
                (
                    f"{rss:.1f} MB"
                    if rss
                    is not None
                    else "—"
                ),

            "detail":
                (
                    f"PID {pid}"
                    if pid
                    else "proces nieaktywny"
                ),

            "state":
                (
                    "ok"
                    if rss is not None
                    and rss < 500
                    else
                    (
                        "warn"
                        if rss is not None
                        else "info"
                    )
                ),
        }
    )

    #
    # Dysk
    #
    disk = _v511_cached(
        "disk_usage",
        120.0,
        lambda:
            shutil.disk_usage(
                "/home/pi"
            ),
    )

    free_gb = (
        disk.free
        / 1024**3
    )

    if free_gb > 5:
        state = "ok"
    elif free_gb > 2:
        state = "warn"
    else:
        state = "bad"

    cards.append(
        {
            "label":
                "Dysk wolny",

            "value":
                f"{free_gb:.1f} GB",

            "detail":
                (
                    f"{100*disk.free/disk.total:.0f}% wolne"
                ),

            "state":
                state,
        }
    )

    #
    # Uptime
    #
    try:

        uptime_s = float(
            Path(
                "/proc/uptime"
            )
            .read_text()
            .split()[0]
        )

    except Exception:

        uptime_s = 0

    cards.append(
        {
            "label":
                "Uptime",

            "value":
                human_uptime(
                    uptime_s
                ),

            "detail":
                "system",

            "state":
                "ok",
        }
    )

    #
    # Restarty + USB
    #
    restarts = detector_restarts()
    resets = usb_resets_24h()

    if resets is None:

        usb_text = "USB: ?"

    else:

        usb_text = (
            f"USB resety 24h: "
            f"{resets}"
        )

    cards.append(
        {
            "label":
                "Stabilność",

            "value":
                (
                    f"{restarts} restartów"
                ),

            "detail":
                usb_text,

            "state":
                (
                    "ok"
                    if (
                        restarts == 0
                        and
                        (
                            resets is None
                            or resets <= 3
                        )
                    )
                    else "warn"
                ),
        }
    )

    owner = owner_data()

    det = detection_data(
        limit=1
    )

    listening_today_s = (
        meteor_listening_seconds_today()
    )

    detections_per_hour = None

    if listening_today_s >= 60.0:

        detections_per_hour = round(
            det["today_count"]
            /
            (
                listening_today_s
                / 3600.0
            ),
            1,
        )


    live_age = None

    try:

        live_age = (
            time.time()
            - LIVE_FILE.stat().st_mtime
        )

    except Exception:

        pass

    live = (
        owner.get(
            "meteorradio_running"
        )
        is True
        and
        live_age is not None
        and
        live_age < 2.5
    )

    return {
        "ok": True,

        "live":
            live,

        "owner":
            owner.get(
                "owner",
                "?"
            ),

        "sondehub_running":
            owner.get(
                "sondehub_running",
                False,
            ),

        "meteorradio_running":
            owner.get(
                "meteorradio_running",
                False,
            ),

        "detections_today":
            det[
                "today_count"
            ],

        "listening_today_s":
            round(
                listening_today_s,
                1,
            ),

        "listening_today_text":
            human_uptime(
                listening_today_s
            ),

        "detections_per_listening_hour":
            detections_per_hour,

        "cards":
            cards,
    }



# ============================================================
# V5_FEATURES_PATCH
# ============================================================

def v5_stats_data():

    try:

        events = csv_events()

        now = datetime.datetime.now()

        dts = [
            x["dt"]
            for x in events
            if isinstance(
                x.get("dt"),
                datetime.datetime,
            )
        ]


        def count_since(
            hours
        ):

            start = (
                now
                -
                datetime.timedelta(
                    hours=hours
                )
            )

            return sum(
                1
                for dt in dts
                if start <= dt <= now
            )


        c24 = count_since(
            24
        )

        c7 = count_since(
            24 * 7
        )

        c30 = count_since(
            24 * 30
        )


        base = (
            now.replace(
                minute=0,
                second=0,
                microsecond=0,
            )
            -
            datetime.timedelta(
                hours=23
            )
        )


        hourly = []

        for i in range(
            24
        ):

            start = (
                base
                +
                datetime.timedelta(
                    hours=i
                )
            )

            end = (
                start
                +
                datetime.timedelta(
                    hours=1
                )
            )

            count = sum(
                1
                for dt in dts
                if start <= dt < end
            )

            hourly.append(
                {
                    "label":
                        start.strftime(
                            "%H"
                        ),
                    "count":
                        count,
                }
            )


        return {
            "ok": True,

            "last_24h": {
                "count": c24,
                "avg_per_hour":
                    round(
                        c24 / 24.0,
                        2,
                    ),
            },

            "last_7d": {
                "count": c7,
                "avg_per_hour":
                    round(
                        c7
                        /
                        (
                            24.0
                            * 7.0
                        ),
                        2,
                    ),
            },

            "last_30d": {
                "count": c30,
                "avg_per_hour":
                    round(
                        c30
                        /
                        (
                            24.0
                            * 30.0
                        ),
                        2,
                    ),
            },

            "hourly":
                hourly,
        }


    except Exception as e:

        return {
            "ok": False,
            "error": repr(
                e
            ),
            "hourly": [],
        }



def live_data():

    payload = {
        "ok": True,
        "live": False,
        "age_s": None,
        "data": None,
    }

    try:

        stat = LIVE_FILE.stat()

        age = max(
            0.0,
            time.time()
            - stat.st_mtime,
        )

        data = json.loads(
            LIVE_FILE.read_text(
                encoding="utf-8"
            )
        )

        payload[
            "age_s"
        ] = round(
            age,
            3,
        )

        payload[
            "live"
        ] = (
            age < 2.5
        )

        payload[
            "data"
        ] = data

    except FileNotFoundError:

        pass

    except Exception as e:

        payload[
            "ok"
        ] = False

        payload[
            "error"
        ] = str(e)

    return payload


HTML = r'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MeteorRadio — GRAVES 143.050 MHz</title>

<style>
*{box-sizing:border-box}
body{
    margin:0;
    background:#0d141b;
    color:#e9eef5;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif
}
main{
    width:min(1500px,96vw);
    margin:20px auto 50px
}
.panel{
    background:#1a242e;
    border:1px solid #354452;
    border-radius:8px;
    padding:18px;
    margin-bottom:14px
}
.header{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:15px;
    flex-wrap:wrap
}
h1{margin:0 0 5px;font-size:24px}
.subtitle{color:#96a5b4;font-size:14px}
.badge{
    display:inline-flex;
    align-items:center;
    gap:7px;
    border-radius:5px;
    padding:8px 13px;
    font-size:12px;
    font-weight:800
}
.badge.live{background:#2d9256}
.badge.off{background:#596675}
.dot{
    width:8px;height:8px;border-radius:50%;background:currentColor
}
.section-title{margin:0 0 13px;font-size:15px}

.health-grid{
    display:grid;
    grid-template-columns:repeat(4,minmax(170px,1fr));
    gap:10px;
    margin-top:16px
}
.health{
    min-height:91px;
    background:#131c24;
    border:1px solid #33414e;
    border-left-width:4px;
    border-radius:6px;
    padding:11px 12px
}
.health.ok{border-left-color:#41d479}
.health.warn{border-left-color:#e3ad42}
.health.bad{border-left-color:#ef5f5f}
.health.info{border-left-color:#539ce8}
.health-label{
    color:#8999a8;
    font-size:11px;
    margin-bottom:7px;
    text-transform:uppercase
}
.health-value{
    font-size:20px;
    font-weight:700;
    font-variant-numeric:tabular-nums
}
.health-detail{
    color:#8392a1;
    font-size:11px;
    margin-top:5px
}

.radio-strip{
    display:grid;
    grid-template-columns:repeat(6,minmax(120px,1fr));
    gap:10px;
    margin-top:14px
}
.metric{
    background:#131c24;
    border:1px solid #33414e;
    border-radius:6px;
    padding:11px 12px
}
.metric-label{
    color:#8999a8;
    font-size:11px;
    margin-bottom:5px
}
.metric-value{
    font-size:19px;
    font-weight:700;
    font-variant-numeric:tabular-nums
}

.metric-detail{
    color:#7f8e9c;
    font-size:10px;
    margin-top:4px
}

.plotwrap{
    position:relative;
    width:100%;
    overflow:hidden;
    background:#060a0e;
    border:1px solid #354452
}
canvas{display:block;width:100%}
#spectrum{height:160px}
#waterfall{height:500px}

.marker{
    position:absolute;
    top:0;bottom:0;
    width:1px;
    pointer-events:none;
    z-index:3
}
.marker.center{
    left:50%;
    background:rgba(255,255,255,.8)
}
.marker.low{
    left:43.333333%;
    background:rgba(65,212,121,.8)
}
.marker.high{
    left:56.666667%;
    background:rgba(65,212,121,.8)
}

.axis{
    display:flex;
    justify-content:space-between;
    padding-top:6px;
    color:#7f8e9c;
    font-size:11px
}
.legend{
    display:flex;
    gap:20px;
    flex-wrap:wrap;
    margin-top:8px;
    color:#8999a8;
    font-size:12px
}
.legend i{
    display:inline-block;
    width:12px;
    height:2px;
    margin-right:5px;
    vertical-align:middle
}
.line-white{background:white}
.line-green{background:#41d479}
#waterfallStatus{
    margin-top:9px;
    color:#8d9baa;
    font-size:12px
}

.detection-summary{
    display:flex;
    gap:12px;
    align-items:center;
    justify-content:space-between;
    flex-wrap:wrap;
    margin-bottom:12px
}
.count{
    font-size:27px;
    font-weight:800
}
.count small{
    display:block;
    font-size:11px;
    font-weight:500;
    color:#8493a2
}

.det-layout{
    display:grid;
    grid-template-columns:360px 1fr;
    gap:14px;
    align-items:start
}
.det-list-panel,
.det-detail-panel{
    background:#131c24;
    border:1px solid #354452;
    border-radius:7px;
    overflow:hidden
}
.det-list-head,
.det-detail-head{
    padding:12px 14px;
    border-bottom:1px solid #354452;
    background:#16202a;
    font-size:13px;
    font-weight:700;
    color:#d7e0e9
}
.det-list{
    overflow:hidden
}

.det-row{
    min-height:52px
}

.det-pager{
    display:grid;
    grid-template-columns:
        1fr
        auto
        1fr;
    align-items:center;
    gap:8px;
    padding:10px;
    border-top:1px solid #354452;
    background:#101820
}

.det-page-btn{
    appearance:none;
    border:1px solid #3d4c5a;
    background:#19242e;
    color:#e1e8ef;
    min-height:36px;
    padding:7px 12px;
    border-radius:5px;
    cursor:pointer;
    font-size:12px;
    font-weight:700
}

.det-page-btn:first-child{
    justify-self:start
}

.det-page-btn:last-child{
    justify-self:end
}

.det-page-btn:hover:not(:disabled){
    background:#22313d;
    border-color:#536576
}

.det-page-btn:disabled{
    opacity:.32;
    cursor:default
}

.det-page-info{
    color:#9aa8b6;
    font-size:12px;
    font-weight:650;
    white-space:nowrap;
    font-variant-numeric:tabular-nums
}
.det-row{
    width:100%;
    text-align:left;
    display:block;
    border:0;
    border-bottom:1px solid #22303c;
    background:#131c24;
    color:#e9eef5;
    padding:12px 14px;
    cursor:pointer
}
.det-row:hover{
    background:#18222c
}
.det-row.active{
    background:#1d2b38;
    box-shadow:inset 3px 0 0 #41d479
}
.det-row-top{
    display:flex;
    justify-content:space-between;
    gap:10px;
    margin-bottom:5px
}
.det-row-time{
    font-size:15px;
    font-weight:750
}
.det-row-snr{
    font-size:13px;
    font-weight:700;
    color:#6fd7ff
}
.det-row-meta{
    color:#93a2b1;
    font-size:12px;
    line-height:1.4
}
.det-row-file{
    color:#70808f;
    font-size:10px;
    margin-top:4px;
    word-break:break-all
}

.det-detail-body{
    padding:14px
}
.det-placeholder{
    padding:28px;
    color:#8ea0b1
}
.det-title{
    font-size:22px;
    font-weight:800;
    margin-bottom:4px
}
.det-subtitle{
    color:#90a0ae;
    font-size:13px;
    margin-bottom:12px
}
.det-large-img{
    width:100%;
    display:block;
    border:1px solid #354452;
    border-radius:6px;
    background:#070b0f;
    margin-bottom:12px
}
.det-metrics{
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:8px;
    margin-bottom:10px
}
.det-item{
    background:#0e161d;
    border-radius:5px;
    padding:8px 9px
}
.det-label{
    color:#8392a1;
    font-size:10px;
    margin-bottom:3px
}
.det-value{
    font-size:14px;
    font-weight:650;
    font-variant-numeric:tabular-nums
}
.filename{
    color:#718190;
    font-size:11px;
    word-break:break-all
}

@media(max-width:1200px){
    .health-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}
    .radio-strip{grid-template-columns:repeat(2,minmax(130px,1fr))}
    .det-layout{grid-template-columns:1fr}
    .det-list{max-height:320px}
}


/* V5_FEATURES_PATCH */

.v5-waterfall-grid{
    display:grid;
    grid-template-columns:minmax(0,1fr) 78px;
    gap:9px;
    align-items:start;
}

.v5-scale-wrap{
    height:500px;
    display:flex;
    flex-direction:column;
}

.v5-scale-title{
    color:#8fa0af;
    font-size:10px;
    text-align:center;
    margin-bottom:3px;
}

#waterfallScale{
    width:78px;
    height:478px;
    background:#060a0e;
    border:1px solid #354452;
}

.v5-stats-grid{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:10px;
    margin-bottom:14px;
}

.v5-stat{
    background:#101820;
    border:1px solid #263745;
    border-radius:8px;
    padding:12px 14px;
}

.v5-stat-label{
    color:#8fa0af;
    font-size:11px;
}

.v5-stat-value{
    color:#e4edf5;
    font-size:25px;
    font-weight:800;
    margin-top:2px;
}

.v5-stat-detail{
    color:#82909d;
    font-size:11px;
    margin-top:3px;
}

.v5-chart-wrap{
    background:#070b0f;
    border:1px solid #354452;
    padding:8px;
}

#v5HourlyChart{
    height:180px;
}

.v5-detection-controls{
    display:flex;
    gap:14px;
    align-items:center;
    flex-wrap:wrap;
    margin:0 0 12px 0;
    color:#99a8b5;
    font-size:12px;
}

.v5-maxhold{
    display:inline-flex;
    align-items:center;
    gap:7px;
    cursor:pointer;
    color:#ffbf66;
}

.v5-maxhold input{
    width:16px;
    height:16px;
}

#detClassification{
    margin:7px 0 10px 0;
    padding:8px 10px;
    border:1px solid #344653;
    border-radius:6px;
    background:#0b1218;
    color:#aebcc8;
    font-size:12px;
    line-height:1.45;
}

#detClassification.meteor{
    border-color:#267847;
    color:#7fe8a2;
}

#detClassification.aircraft{
    border-color:#a0742c;
    color:#ffd27b;
}

#detClassification.interference{
    border-color:#8e3940;
    color:#ff8d95;
}

#detClassification.uncertain{
    border-color:#485c6d;
    color:#aebcc8;
}

@media(max-width:850px){

    .v5-stats-grid{
        grid-template-columns:1fr;
    }

    .v5-waterfall-grid{
        grid-template-columns:minmax(0,1fr) 62px;
    }
}




/* LIVE_WATERFALL_REMOVED_CPU_V1 */
.live-waterfall-disabled{
    display:none !important;
}

/*
 * Peak oraz SNR widma pochodziły z ciągłego live FFT.
 * Po jego usunięciu chowamy te dwie karty.
 */
.metric:has(#peak),
.metric:has(#snr),
.metric-card:has(#peak),
.metric-card:has(#snr){
    display:none !important;
}




/* V53_DETECTION_FILTERS_FAVORITES */

.v5-detection-controls{
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:10px 14px;
}

.v53-maxhold-switch{
    display:inline-flex !important;
    align-items:center;
    gap:7px;
    cursor:pointer;
    user-select:none;
    padding:6px 10px;
    border:1px solid #526170;
    border-radius:6px;
    background:#101a22;
}

.v53-maxhold-switch strong{
    display:inline-block;
    min-width:34px;
    text-align:center;
    padding:2px 6px;
    border-radius:4px;
    font-size:11px;
    color:#ff8585;
    background:#2a1114;
    border:1px solid #67323a;
}

.v53-maxhold-switch.on strong{
    color:#70e59a;
    background:#10291b;
    border-color:#285b3b;
}

.v53-filter-label{
    display:inline-flex;
    align-items:center;
    gap:7px;
    color:#aebdca;
    font-size:12px;
}

#v53DetectionFilter{
    background:#101a22;
    color:#e5edf3;
    border:1px solid #435361;
    border-radius:5px;
    padding:6px 9px;
    outline:none;
}

#v53DetectionFilter:focus{
    border-color:#53c9ff;
}

.v53-recalc{
    background:#14232d;
    color:#aebdca;
    border:1px solid #435361;
    border-radius:5px;
    padding:6px 9px;
    cursor:pointer;
}

.v53-recalc:hover{
    color:#fff;
    border-color:#657989;
}

.v53-recalc:disabled{
    opacity:.45;
    cursor:wait;
}

.v53-filter-status{
    font-size:11px;
    color:#8294a4;
}

.v53-row-right{
    display:flex;
    align-items:center;
    gap:8px;
    margin-left:auto;
}

.v53-confidence{
    font-size:11px;
    color:#f5c75d;
    font-weight:700;
    min-width:34px;
    text-align:right;
}

.v53-star{
    font-size:21px;
    line-height:1;
    color:#687784;
    cursor:pointer;
    padding:0 2px;
    transition:
        transform .12s ease,
        color .12s ease;
}

.v53-star:hover{
    transform:scale(1.18);
    color:#ffd75f;
}

.v53-star.on{
    color:#ffd24e;
}

.det-row-time{
    font-size:14px;
}




/* V54_CONFIDENCE_DIRECT_COLOR_FIX */

.v53-confidence.v54-conf-green{
    color:#39e675 !important;
    font-weight:900 !important;
}

.v53-confidence.v54-conf-yellow{
    color:#ffd43b !important;
    font-weight:900 !important;
}

.v53-confidence.v54-conf-orange{
    color:#ff922b !important;
    font-weight:900 !important;
}

.v53-confidence.v54-conf-red{
    color:#ff5c5c !important;
    font-weight:900 !important;
}




/* V55_DETECTION_SORT */

#v55DetectionSort{
    background:#101a22;
    color:#e5edf3;
    border:1px solid #435361;
    border-radius:5px;
    padding:6px 9px;
    outline:none;
}

#v55DetectionSort:focus{
    border-color:#53c9ff;
}



/* SCORE_LEFT_OF_DB_CSS */
.det-right,
.det-meta-right,
.det-row-right,
.detection-right,
.list-right,
.row-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.det-score,
.score-badge,
[data-score-badge] {
  order: 1 !important;
  margin-right: 0 !important;
  margin-left: 0 !important;
}

.det-snr,
.snr-value,
[data-snr] {
  order: 2 !important;
}

</style>

<!-- MR_REMOVE_DUPLICATE_SCORE_BADGES_V2 -->
<style id="mr-score-dedupe-style">
  .mr-score-hidden { display:none !important; }
</style>

<script>
(function () {
  const MARK = 'MR_REMOVE_DUPLICATE_SCORE_BADGES_V2';
  if (window.__mr_score_dedupe_v2__) return;
  window.__mr_score_dedupe_v2__ = true;

  function txt(el) {
    return ((el && el.textContent) ? el.textContent : '').replace(/\s+/g, ' ').trim();
  }

  function isScoreToken(el) {
    if (!el) return false;
    const t = txt(el);
    if (!/^[1-7]\/7$/.test(t)) return false;
    const tag = (el.tagName || '').toLowerCase();
    return ['span','div','small','strong','b'].includes(tag);
  }

  function getRows() {
    let rows = Array.from(document.querySelectorAll(
      '.detection-item, .detection-row, .det-row, .list-item, [data-detection-item], [data-row-type="detection"]'
    ));

    if (rows.length) return rows;

    return Array.from(document.querySelectorAll('div, li, article'))
      .filter(el => {
        const t = txt(el);
        return t.includes('.npz') && t.includes('dB') && /doppler/i.test(t);
      })
      .slice(0, 40);
  }

  function dedupeRow(row) {
    const candidates = Array.from(row.querySelectorAll('span,div,small,strong,b'))
      .filter(isScoreToken);

    if (candidates.length <= 1) return;

    const visible = candidates.filter(el => el.offsetParent !== null);
    const pool = visible.length ? visible : candidates;

    let keep = null;
    let best = -Infinity;

    for (const el of pool) {
      const r = el.getBoundingClientRect();
      const score = r.left;   // chcemy zostawić ten najbardziej po PRAWEJ
      if (score > best) {
        best = score;
        keep = el;
      }
    }

    for (const el of candidates) {
      if (el !== keep) {
        el.remove();
      }
    }
  }

  function run() {
    try {
      const rows = getRows();
      rows.forEach(dedupeRow);
    } catch (e) {
      // celowo cicho
    }
  }

  window.addEventListener('load', () => setTimeout(run, 150));
  document.addEventListener('DOMContentLoaded', () => setTimeout(run, 150));

  // lekkie odświeżanie po renderze listy, bez MutationObserver
  
    /* SCORE_DEDUPE interval disabled */
    
})();
</script>


<!-- MR_ACTIVE_ROW_STABLE_LAYOUT_V1 -->
<style id="mr-active-row-stable-layout-v1">

/*
 * Zaznaczony rekord nie może zmieniać geometrii.
 * Zielone zaznaczenie zostaje, ale nie zabiera miejsca.
 */

.det-row,
.det-row.active{
    box-sizing:border-box !important;
}


/*
 * Górny wiersz zawsze w jednej linii:
 * DATA/GODZINA | dB | OCENA | ★
 */
.det-row-top{
    display:flex !important;
    flex-wrap:nowrap !important;
    align-items:center !important;
    min-width:0 !important;
    gap:5px !important;
}


/*
 * Data + godzina nigdy nie przechodzą do drugiej linii.
 */
.det-row-time{
    flex:1 1 auto !important;
    min-width:0 !important;
    white-space:nowrap !important;
    line-height:1.2 !important;
}


/*
 * Prawa strona nie może ściskać się ani zawijać.
 */
.det-row-snr,
.det-row-top .v53-star,
.det-row-top .v562-score,
.det-row-top .v562-score-badge,
.det-row-top .mr-score,
.det-row-top .mr-score-badge{
    flex:0 0 auto !important;
    white-space:nowrap !important;
}


/*
 * ACTIVE wcześniej zabierał kilka px szerokości przez lewy border.
 * Zamiast borderu używamy wewnętrznego cienia:
 * efekt wizualny zostaje, szerokość treści nie zmienia się.
 */
.det-row.active{
    border-left-color:transparent !important;
    box-shadow:
        inset 3px 0 0 #49d17d !important;
}


/* MR_REAL_TOP_NAV_8094_V1 */

.mr-header-right{
    display:flex;
    align-items:center;
    gap:8px;
    margin-left:auto;
}

.mr-nav-actions{
    display:flex;
    align-items:center;
    gap:8px;
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

@media(max-width:900px){

    .mr-header-right{
        flex-wrap:wrap;
        justify-content:flex-end;
    }

    .mr-nav-actions{
        flex-wrap:wrap;
        justify-content:flex-end;
    }
}

</style>

</head>

<body>
<main>

<section class="panel">
    <div class="header">
        <div>
            <h1>☄ MeteorRadio — GRAVES</h1>
            <div class="subtitle">RTL-SDR Blog V4 · 143.050 MHz · station dashboard</div>
        </div>

        <div class="mr-header-right">

            <div class="mr-nav-actions">

                <a
                    class="mr-nav-btn"
                    href="#" onclick="location.href=location.protocol+'//'+location.hostname+':8096/'; return false;"
                >
                    Ulubione
                </a>

                <a
                    class="mr-nav-btn"
                    href="#" onclick="location.href=location.protocol+'//'+location.hostname+':8097/'; return false;"
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

            <div id="liveBadge" class="badge off">
                <span class="dot"></span>
                <span id="liveText">OCZEKIWANIE</span>
            </div>

        </div>
    </div>

    <div id="healthGrid" class="health-grid"></div>

    <div class="radio-strip">
        <div class="metric">
            <div class="metric-label">Właściciel RTL-SDR</div>
            <div id="owner" class="metric-value">—</div>
        </div>
        <div class="metric">
            <div class="metric-label">Częstotliwość</div>
            <div class="metric-value">143.050000</div>
        </div>
        <div class="metric">
            <div class="metric-label">Peak</div>
            <div id="peak" class="metric-value">—</div>
        </div>
        <div class="metric">
            <div class="metric-label">SNR widma</div>
            <div id="snr" class="metric-value">—</div>
        </div>
        <div class="metric">
            <div class="metric-label">Detekcje dziś</div>
            <div id="detectionsToday" class="metric-value">—</div>
        </div>

        <div class="metric">
            <div class="metric-label">
                Średnia detekcji / h
            </div>

            <div
                id="detectionsPerHour"
                class="metric-value">
                —
            </div>

            <div
                id="listeningToday"
                class="metric-detail">
                nasłuch dziś: —
            </div>
        </div>
    </div>
</section>


<section class="panel live-waterfall-disabled">
    <h2 class="section-title">LIVE WATERFALL</h2>

    <div class="v5-waterfall-grid">

        <div>

            <div class="plotwrap">

                <canvas
                    id="waterfall"
                    width="1200"
                    height="500">
                </canvas>

                <span class="marker low"></span>
                <span class="marker high"></span>

            </div>

            <div class="axis">
                <span>−1.5 kHz</span>
                <span>−1.0</span>
                <span>−0.5</span>
                <span>143.050 MHz</span>
                <span>+0.5</span>
                <span>+1.0</span>
                <span>+1.5 kHz</span>
            </div>

        </div>

        <div class="v5-scale-wrap">

            <div class="v5-scale-title">
                dB<br>nad tłem
            </div>

            <canvas
                id="waterfallScale"
                width="78"
                height="478">
            </canvas>

        </div>

    </div>

    <div id="waterfallStatus">
        ładowanie historii 5 min…
    </div>

</section>



<section class="panel" id="v5Stats">

    <h2 class="section-title">
        STATYSTYKI DETEKCJI
    </h2>

    <div class="subtitle" style="margin-bottom:12px">
        okna kroczące · średnia/h jest średnią zegarową dla danego okresu
    </div>

    <div class="v5-stats-grid">

        <div class="v5-stat">
            <div class="v5-stat-label">
                OSTATNIE 24 H
            </div>
            <div
                class="v5-stat-value"
                id="v5Count24">
                —
            </div>
            <div
                class="v5-stat-detail"
                id="v5Rate24">
                —
            </div>
        </div>

        <div class="v5-stat">
            <div class="v5-stat-label">
                OSTATNIE 7 DNI
            </div>
            <div
                class="v5-stat-value"
                id="v5Count7">
                —
            </div>
            <div
                class="v5-stat-detail"
                id="v5Rate7">
                —
            </div>
        </div>

        <div class="v5-stat">
            <div class="v5-stat-label">
                OSTATNIE 30 DNI
            </div>
            <div
                class="v5-stat-value"
                id="v5Count30">
                —
            </div>
            <div
                class="v5-stat-detail"
                id="v5Rate30">
                —
            </div>
        </div>

    </div>

    <div class="v5-chart-wrap">

        <canvas
            id="v5HourlyChart"
            width="1200"
            height="180">
        </canvas>

    </div>

</section>

<section class="panel">
    <div class="detection-summary">
        <div>
            <h2 class="section-title" style="margin-bottom:3px">DETEKCJE</h2>
            <div class="subtitle">lista po lewej · szczegóły wybranej detekcji po prawej</div>
        </div>
        <div class="count">
            <span id="detCount">0</span>
            <small>dzisiaj</small>
        </div>
    </div>

    
    <div class="v5-detection-controls">

        
        <!-- V53_DETECTION_FILTERS_FAVORITES -->

        <label
            class="v5-maxhold v53-maxhold-switch"
            id="v53MaxHoldWrap"
            title="Kliknij, aby włączyć lub wyłączyć MAX HOLD">

            <input
                type="checkbox"
                id="maxHoldToggle"
                checked>

            <span>MAX HOLD</span>

            <strong id="maxHoldState">
                ON
            </strong>

        </label>

        <label class="v53-filter-label">

            <span>Filtr:</span>

            <select id="v53DetectionFilter">

                <option value="all">
                    Wszystkie
                </option>

                <option value="fav">
                    ★ Ulubione
                </option>

                <option value="60">
                    Pewność ≥ 60%
                </option>

                <option value="70">
                    Pewność ≥ 70%
                </option>

                <option value="80">
                    Pewność ≥ 80%
                </option>

                <option value="90">
                    Pewność ≥ 90%
                </option>

            </select>

        </label>

        <!-- V55_DETECTION_SORT -->
        <label class="v53-filter-label">

            <span>Sortuj:</span>

            <select id="v55DetectionSort">
                <option value="newest">
                    Najnowsze
                </option>

                <option value="oldest">
                    Najstarsze
                </option>

                <option value="snr_desc">
                    SNR ↓
                </option>

                <option value="snr_asc">
                    SNR ↑
                </option>

                <option value="liked_first">
                    Polubiane
                </option>

                <option value="unliked_first">
                    Niepolubiane
                </option>

                <option value="score_desc">
                    OCENA ↓
                </option>

                <option value="score_asc">
                    OCENA ↑
                </option>
</select>

        </label>


        <button
            type="button"
            id="v53Recalc"
            class="v53-recalc"
            title="Przelicz brakujące klasyfikacje">
            ↻ Przelicz pewność
        </button>

        <span id="v53FilterStatus"
              class="v53-filter-status">
        </span>


        <span>
            klasyfikacja: heurystyka kształtu sygnału,
            nie automatyczne potwierdzenie meteoru
        </span>

    </div>

<div class="det-layout">
        <div class="det-list-panel">

            <div class="det-list-head">
                Lista detekcji · 8 na stronę
            </div>

            <div
                id="detList"
                class="det-list">
            </div>

            <div
                id="detPager"
                class="det-pager">

                <button
                    id="detPrev"
                    class="det-page-btn"
                    type="button">
                    ← Nowsze
                </button>

                <div
                    id="detPageInfo"
                    class="det-page-info">
                    Strona 1 / 1
                </div>

                <button
                    id="detNext"
                    class="det-page-btn"
                    type="button">
                    Starsze →
                </button>

            </div>

        </div>

        <div class="det-detail-panel">
            <div class="det-detail-head">Szczegóły detekcji</div>
            <div id="detDetailBody" class="det-detail-body">
                <div id="detPlaceholder" class="det-placeholder">
                    Wybierz detekcję z listy po lewej.
                </div>

                <div id="detDetail" style="display:none">
                    <div id="detTitle" class="det-title">—</div>
                    <div id="detSubtitle" class="det-subtitle">—</div>

                    <img id="detImage" class="det-large-img" src="" alt="Spektrogram detekcji">

                    <div class="det-metrics">
                        <div class="det-item">
                            <div class="det-label">SNR</div>
                            <div id="detSNR" class="det-value">—</div>
                        </div>
                        <div class="det-item">
                            <div class="det-label">Czas</div>
                            <div id="detDuration" class="det-value">—</div>
                        </div>
                        <div class="det-item">
                            <div class="det-label">Częstotliwość</div>
                            <div id="detFreq" class="det-value">—</div>
                        </div>
                        <div class="det-item">
                            <div class="det-label">Doppler</div>
                            <div id="detDoppler" class="det-value">—</div>
                        </div>
                    </div>

                    <div id="detFile" class="filename">—</div>
                </div>
            </div>
        </div>
    </div>
</section>

</main>

<script>
const waterfall = document.getElementById("waterfall");
const waterfallCtx = waterfall.getContext("2d");

let lastTimestamp = null;

let liveNoiseFloorDb = null;
let liveWaterfallRows = 0;

let detectionsCache = [];
let selectedDetectionFile = null;
let detailImageSeq = 0;

let detectionPage = 1;
let detectionTotalPages = 1;

const DETECTIONS_PER_PAGE = 8;

let liveContrastDb = 18.0;
let lastWaterfallAdvance = 0;
let maxHoldEnabled = true;
let v5DetailSeq = 0;

const V5_HISTORY_STEP_MS = 600;



function esc(x){
    return String(x ?? "")
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll('"',"&quot;");
}

function fmt(value, suffix=""){
    if(value===null || value===undefined){ return "—"; }
    return String(value) + suffix;
}

function median(values){
    if(!values.length){ return 0; }
    const x=[...values].sort((a,b)=>a-b);
    const n=x.length;
    const m=Math.floor(n/2);
    return n%2 ? x[m] : (x[m-1]+x[m])/2;
}

function color(t){

    t=Math.max(
        0,
        Math.min(
            1,
            t
        )
    );

    const stops=[
        [0.00,   0,   0,   4],
        [0.16,  31,  12,  72],
        [0.32,  85,  15, 109],
        [0.48, 147,  38, 103],
        [0.64, 207,  68,  70],
        [0.80, 244, 120,  27],
        [0.92, 252, 190,  48],
        [1.00, 252, 255, 164]
    ];

    for(
        let i=0;
        i<stops.length-1;
        i++
    ){

        const a=stops[i];
        const b=stops[i+1];

        if(
            t>=a[0]
            &&
            t<=b[0]
        ){

            const q=
                (
                    t-a[0]
                )
                /
                (
                    b[0]-a[0]
                );

            return [
                Math.round(
                    a[1]
                    +(b[1]-a[1])*q
                ),

                Math.round(
                    a[2]
                    +(b[2]-a[2])*q
                ),

                Math.round(
                    a[3]
                    +(b[3]-a[3])*q
                )
            ];
        }
    }

    return [
        252,
        255,
        164
    ];
}

function drawSpectrum(values){
    if(!values.length){ return; }
    const w=spectrum.width;
    const h=spectrum.height;

    spectrumCtx.fillStyle="#060a0e";
    spectrumCtx.fillRect(0,0,w,h);

    const base=median(values);
    const rel=values.map(v=>v-base);
    const maxDb=Math.max(12,...rel);

    spectrumCtx.beginPath();
    spectrumCtx.strokeStyle="#62c7ea";
    spectrumCtx.lineWidth=1.5;

    rel.forEach((v,i)=>{
        const x=i*(w-1)/Math.max(1,rel.length-1);
        const clipped=Math.max(-3,Math.min(maxDb,v));
        const y=h-5-(((clipped+3)/(maxDb+3))*(h-10));
        if(i===0){ spectrumCtx.moveTo(x,y); }
        else{ spectrumCtx.lineTo(x,y); }
    });

    spectrumCtx.stroke();
}



// V5_DARKER_LIVE_SCALE_V2
// wizualizacja:
// black floor = +4 dB
// contrast ≈18..30 dB
// szybki attack floor / wolniejszy release

function v5Percentile(values,q){

    const x=
        values
        .filter(Number.isFinite)
        .slice()
        .sort((a,b)=>a-b);

    if(!x.length){
        return 0;
    }

    const pos=
        Math.max(
            0,
            Math.min(
                x.length-1,
                Math.round(
                    q
                    *
                    (
                        x.length-1
                    )
                )
            )
        );

    return x[pos];
}


function v5UpdateScale(values){

    const finite=
        values.filter(
            Number.isFinite
        );

    if(!finite.length){
        return;
    }

    const rowFloor=
        median(finite);

    const high=
        v5Percentile(
            finite,
            0.98
        );

    if(
        liveNoiseFloorDb
        === null
    ){

        liveNoiseFloorDb=
            rowFloor;

    }else{

        /*
         * Bardzo wolny floor.
         * Nie jest to AGC tunera.
         */
        
        const floorAlpha =
            (
                rowFloor > liveNoiseFloorDb
                ? 0.18
                : 0.02
            );

        liveNoiseFloorDb =
            (
                1.0 - floorAlpha
            )
            * liveNoiseFloorDb
            +
            floorAlpha
            * rowFloor;

    }


    const target=
        Math.max(
            18,
            Math.min(
                30,
                (
                    high
                    -
                    liveNoiseFloorDb
                )
                +
                10
            )
        );


    liveContrastDb=
        (
            0.995
            *
            liveContrastDb
        )
        +
        (
            0.005
            *
            target
        );
}


function v5RgbForDb(value){

    if(
        liveNoiseFloorDb
        === null
    ){
        return [0,0,0];
    }

    const delta=
        value
        -
        liveNoiseFloorDb;


    if(delta < 4.0){
        return [0,0,0];
    }


    const t=
        Math.max(
            0,
            Math.min(
                1,
                (
                    delta - 4.0
                )
                /
                Math.max(12, liveContrastDb)
            )
        );

    return color(t);
}


function v5DrawWaterfallRow(values,y){

    const w=
        waterfall.width;

    const n=
        values.length;

    if(!n){
        return;
    }


    const row=
        waterfallCtx.createImageData(
            w,
            1
        );


    for(
        let x=0;
        x<w;
        x++
    ){

        const fx=
            x
            *
            (
                n-1
            )
            /
            Math.max(
                1,
                w-1
            );

        const i=
            Math.floor(
                fx
            );

        const j=
            Math.min(
                n-1,
                i+1
            );

        const f=
            fx-i;

        const value=
            (
                Number(
                    values[i]
                )
                *
                (
                    1-f
                )
            )
            +
            (
                Number(
                    values[j]
                )
                *
                f
            );


        const rgb=
            v5RgbForDb(
                value
            );

        const p=
            x*4;

        row.data[p]=rgb[0];
        row.data[p+1]=rgb[1];
        row.data[p+2]=rgb[2];
        row.data[p+3]=255;
    }


    waterfallCtx.putImageData(
        row,
        0,
        y
    );
}


function v5DrawDbScale(){

    const c=
        document.getElementById(
            "waterfallScale"
        );

    if(!c){
        return;
    }

    const ctx=
        c.getContext(
            "2d"
        );

    const w=c.width;
    const h=c.height;

    ctx.fillStyle="#060a0e";
    ctx.fillRect(
        0,
        0,
        w,
        h
    );


    const gradW=
        Math.max(
            18,
            w-43
        );


    for(
        let y=0;
        y<h;
        y++
    ){

        const t=
            1
            -
            y
            /
            Math.max(
                1,
                h-1
            );

        const rgb=
            color(t);

        ctx.fillStyle=
            `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;

        ctx.fillRect(
            0,
            y,
            gradW,
            1
        );
    }


    ctx.font="10px sans-serif";
    ctx.fillStyle="#b3c0cb";
    ctx.textBaseline="middle";


    [4,8,12,18,24].forEach(
        db=>{

            const ratio=
                Math.max(
                    0,
                    Math.min(
                        1,
                        (
                            db - 4
                        )
                        /
                        Math.max(12, liveContrastDb)
                    )
                );

            const y=
                h
                -
                ratio
                *
                (
                    h-1
                );

            ctx.fillStyle="#627381";
            ctx.fillRect(
                gradW,
                y,
                4,
                1
            );

            ctx.fillStyle="#b3c0cb";
            ctx.fillText(
                "+"+db,
                gradW+7,
                Math.max(
                    7,
                    Math.min(
                        h-7,
                        y
                    )
                )
            );
        }
    );
}


async function v5RestoreHistory(){
    // LIVE_WATERFALL_REMOVED_CPU_V1
    return;
}



function addWaterfall(values){

    if(!values.length){
        return;
    }

    v5UpdateScale(values);

    const now=
        performance.now();

    const advance=
        (
            now
            - lastWaterfallAdvance
            >= V5_HISTORY_STEP_MS
        );

    if(advance){

        waterfallCtx.drawImage(
            waterfall,
            0,
            0,
            waterfall.width,
            waterfall.height-1,
            0,
            1,
            waterfall.width,
            waterfall.height-1
        );

        lastWaterfallAdvance=
            now;

        liveWaterfallRows++;
    }

    v5DrawWaterfallRow(
        values,
        0
    );

    v5DrawDbScale();
}

function setLive(listening){
    // V58_LISTENING_BADGE_FIX
    //
    // Badge oznacza stan faktycznego nasłuchu
    // MeteorRadio, nie stary live-waterfall.
    //
    const badge=document.getElementById("liveBadge");
    const text=document.getElementById("liveText");

    if(listening){
        badge.className="badge live";
        text.textContent="NASŁUCH";
    }else{
        badge.className="badge off";
        text.textContent="OCZEKIWANIE";
    }
}

async function refreshLive(){
    // LIVE_WATERFALL_REMOVED_CPU_V1
    return;
}

async function refreshHealth(){
    try{
        const r=await fetch("/api/status?t="+Date.now(),{cache:"no-store"});
        const d=await r.json();

        // V57_COMPACT_HEALTH_HEADER
        //
        // 1. W miejsce karty "Stabilność"
        //    pokazujemy średnią detekcji na godzinę.
        //
        // 2. Stary dolny rząd metryk pozostaje w DOM,
        //    żeby istniejący JS mógł nadal bezpiecznie
        //    aktualizować jego elementy, ale nie jest
        //    wyświetlany użytkownikowi.
        //

        const v57Rate =
            d.detections_per_listening_hour;

        d.cards = (d.cards || []).map(
            card => {

                if(
                    String(
                        card?.label || ""
                    ).trim()
                    ===
                    "Stabilność"
                ){

                    return {
                        ...card,

                        label:
                            "Średnia detekcji / h",

                        value:
                            (
                                v57Rate === null
                                ||
                                v57Rate === undefined
                            )
                            ?
                            "—"
                            :
                            Number(
                                v57Rate
                            ).toFixed(1)
                            +
                            "/h",

                        detail:
                            "nasłuch dziś: "
                            +
                            (
                                d.listening_today_text
                                ||
                                "—"
                            ),

                        state:
                            "ok"
                    };
                }

                return card;
            }
        );


        //
        // Dolny rząd:
        // owner / częstotliwość / peak / SNR /
        // detekcje dziś / rate.
        //
        // #owner znajduje się w pierwszej .metric,
        // więc chowamy cały wspólny kontener.
        //

        const v57Owner =
            document.getElementById(
                "owner"
            );

        const v57OwnerCard =
            v57Owner
            ?
            v57Owner.closest(
                ".metric"
            )
            :
            null;

        if(
            v57OwnerCard
            &&
            v57OwnerCard.parentElement
        ){
            v57OwnerCard
                .parentElement
                .style
                .display = "none";
        }


        const v58Listening=(
            d.meteorradio_running === true
            &&
            String(
                d.owner || ""
            ).toUpperCase() === "METEOR"
        );

        setLive(
            v58Listening
        );
        document.getElementById("owner").textContent=d.owner || "—";
        document.getElementById("detectionsToday").textContent=d.detections_today ?? 0;

        const rate=
            d.detections_per_listening_hour;

        document.getElementById(
            "detectionsPerHour"
        ).textContent=
            (
                rate===null
                ||
                rate===undefined
            )
            ? "—"
            : Number(rate).toFixed(1)+"/h";

        document.getElementById(
            "listeningToday"
        ).textContent=
            "nasłuch dziś: "
            +(d.listening_today_text || "—");

        const grid=document.getElementById("healthGrid");

        const v511Cards=
            d.cards || [];

        const v511Signature=
            JSON.stringify(
                v511Cards
            );

        if(
            window.__v511HealthSignature
            !==
            v511Signature
        ){

            grid.innerHTML=
                v511Cards.map(x=>`
                    <div class="health ${esc(x.state)}">
                        <div class="health-label">${esc(x.label)}</div>
                        <div class="health-value">${esc(x.value)}</div>
                        <div class="health-detail">${esc(x.detail)}</div>
                    </div>
                `).join("");

            window.__v511HealthSignature=
                v511Signature;
        }
    }catch(e){}
}

function mhzText(x){
    if(x===null || x===undefined){ return "—"; }
    return (x/1e6).toFixed(6)+" MHz";
}

function renderDetectionDetail(item){

    const placeholder=
        document.getElementById(
            "detPlaceholder"
        );

    const detail=
        document.getElementById(
            "detDetail"
        );

    const subtitle=
        document.getElementById(
            "detSubtitle"
        );

    const image=
        document.getElementById(
            "detImage"
        );


    /*
     * Każde kliknięcie dostaje własny numer.
     * Spóźniona odpowiedź poprzedniego obrazka
     * nie może nadpisać aktualnego stanu.
     */
    const seq=
        ++detailImageSeq;


    if(!item){

        placeholder.style.display=
            "block";

        detail.style.display=
            "none";

        image.onload=null;
        image.onerror=null;

        image.removeAttribute(
            "src"
        );

        return;
    }


    placeholder.style.display=
        "none";

    detail.style.display=
        "block";


    /*
     * TEKST I PARAMETRY ZMIENIAMY NATYCHMIAST.
     */
    document.getElementById(
        "detTitle"
    ).textContent=
        "☄ "
        +(item.time || "—");


    document.getElementById(
        "detSNR"
    ).textContent=
        fmt(
            item.snr_db,
            " dB"
        );


    document.getElementById(
        "detDuration"
    ).textContent=
        fmt(
            item.duration_s,
            " s"
        );


    document.getElementById(
        "detFreq"
    ).textContent=
        mhzText(
            item.frequency_hz
        );


    document.getElementById(
        "detDoppler"
    ).textContent=
        fmt(
            item.doppler_hz,
            " Hz"
        );


    document.getElementById(
        "detFile"
    ).textContent=
        (item.file || "—")
        +" · "
        +fmt(
            item.size_mb,
            " MB"
        );


    /*
     * STARY OBRAZ NATYCHMIAST ZNIKA.
     */
    image.onload=null;
    image.onerror=null;

    image.style.visibility=
        "hidden";

    image.style.opacity=
        "0";

    image.removeAttribute(
        "src"
    );


    subtitle.textContent=
        "Ładowanie obrazu detekcji…";


    const url=
        "/detection-v5.png?file="
        +encodeURIComponent(
            item.file
        )
        +"&v=41";


    /*
     * Najpierw przeglądarka ma wyczyścić
     * stary obraz, potem rozpoczynamy nowe
     * żądanie.
     */
    requestAnimationFrame(
        ()=>{

            image.onload=
                ()=>{

                    if(
                        seq
                        !==
                        detailImageSeq
                    ){
                        return;
                    }

                    image.style.visibility=
                        "visible";

                    image.style.opacity=
                        "1";

                    subtitle.textContent=
                        "Obraz detekcji gotowy";
                };


            image.onerror=
                ()=>{

                    if(
                        seq
                        !==
                        detailImageSeq
                    ){
                        return;
                    }

                    image.style.visibility=
                        "hidden";

                    subtitle.textContent=
                        "Błąd ładowania obrazu detekcji";
                };


            image.src=url;
        }
    );
}




const v5RenderDetectionDetailBase=
    renderDetectionDetail;


renderDetectionDetail=
    function(item){

        v5RenderDetectionDetailBase(
            item
        );


        if(!item){
            return;
        }


        const seq=
            ++v5DetailSeq;


        /*
         * Oryginalna funkcja nadal obsługuje
         * chowanie starego obrazu i race condition.
         * V5 tylko podmienia końcowy URL.
         */
        requestAnimationFrame(
            ()=>{

                requestAnimationFrame(
                    ()=>{

                        if(
                            seq
                            !==
                            v5DetailSeq
                        ){
                            return;
                        }


                        const image=
                            document.getElementById(
                                "detImage"
                            )
                            ||
                            document.querySelector(
                                "#detDetail img"
                            );


                        if(image){

                            image.src=
                                "/detection-v5.png?file="
                                +
                                encodeURIComponent(
                                    item.file
                                )
                                +
                                "&maxhold="
                                +
                                (
                                    maxHoldEnabled
                                    ? "1"
                                    : "0"
                                )
                                +
                                "&v=50";
                        }
                    }
                );
            }
        );


        v5LoadClassification(
            item,
            seq
        );
    };


async function v5LoadClassification(
    item,
    seq
){

    const detail=
        document.getElementById(
            "detDetail"
        );


    if(!detail){
        return;
    }


    let box=
        document.getElementById(
            "detClassification"
        );


    if(!box){

        box=
            document.createElement(
                "div"
            );

        box.id=
            "detClassification";

        box.className=
            "uncertain";

        detail.insertBefore(
            box,
            detail.firstChild
        );
    }


    box.className=
        "uncertain";

    box.textContent=
        "Klasyfikacja heurystyczna: analizuję kształt…";


    try{

        const r=
            await fetch(
                "/api/classification?file="
                +
                encodeURIComponent(
                    item.file
                )
                +
                "&t="
                +
                Date.now(),
                {
                    cache:"no-store"
                }
            );


        const d=
            await r.json();


        if(
            seq
            !==
            v5DetailSeq
        ){
            return;
        }


        if(!d.ok){

            box.className=
                "uncertain";

            box.textContent=
                "Klasyfikacja: brak wyniku";

            return;
        }


        box.className=
            d.kind
            ||
            "uncertain";


        const m=
            d.metrics
            ||
            {};


        box.textContent=
            "HEURYSTYKA: "
            +
            (
                d.label
                ||
                "niepewne"
            )
            +
            " · pewność "
            +
            (
                d.confidence
                ??
                "—"
            )
            +
            "%"
            +
            " · ślad "
            +
            (
                m.active_duration_s
                ??
                "—"
            )
            +
            " s"
            +
            " · span "
            +
            (
                m.frequency_span_hz
                ??
                "—"
            )
            +
            " Hz"
            +
            " · drift "
            +
            (
                m.drift_hz
                ??
                "—"
            )
            +
            " Hz"
            +
            " · "
            +
            (
                d.explanation
                ||
                ""
            );


    }catch(e){

        if(
            seq
            ===
            v5DetailSeq
        ){

            box.className=
                "uncertain";

            box.textContent=
                "Klasyfikacja: błąd analizy";
        }
    }
}



function renderDetectionPager(){

    const prev =
        document.getElementById(
            "detPrev"
        );

    const next =
        document.getElementById(
            "detNext"
        );

    const info =
        document.getElementById(
            "detPageInfo"
        );


    let page =
        Number(
            detectionPage
        );

    let pages =
        Number(
            detectionTotalPages
        );


    if(
        !Number.isFinite(page)
        ||
        page < 1
    ){
        page = 1;
    }


    if(
        !Number.isFinite(pages)
        ||
        pages < 1
    ){
        pages = 1;
    }


    if(page > pages){
        page = pages;
    }


    detectionPage = page;
    detectionTotalPages = pages;


    if(info){

        info.textContent =
            "Strona "
            + page
            + " / "
            + pages;
    }


    if(prev){

        prev.textContent =
            "← Nowsze";

        prev.disabled =
            page <= 1;
    }


    if(next){

        next.textContent =
            "Starsze →";

        next.disabled =
            page >= pages;
    }
}

function renderDetectionList(list){
    const el=document.getElementById("detList");

    if(!list.length){
        el.innerHTML='<div class="det-placeholder">Brak zapisanych detekcji.</div>';
        renderDetectionDetail(null);
        return;
    }

    // V52_DETAIL_CLICK_ONLY_V1
    //
    // Lista może odświeżać się automatycznie,
    // ale nie wybieramy detekcji automatycznie.
    //
    // Ciężki renderer V5 uruchomi się dopiero
    // po świadomym kliknięciu użytkownika.
    //
    if(
        selectedDetectionFile
        &&
        !list.some(
            x=>x.file===selectedDetectionFile
        )
    ){
        selectedDetectionFile=null;
    }

    el.innerHTML=list.map(x=>{
        const active = x.file===selectedDetectionFile ? "active" : "";
        return `
            <button class="det-row ${active}" data-file="${esc(x.file)}">
                <div class="det-row-top">
                    <div class="det-row-time">
                    ☄ ${esc(v53DateText(x.time || x.time_short || "—"))}
                </div>

                <div class="v53-row-right">

                    <span class="v53-confidence ${v54ConfidenceClass(x.file)}">
                        ${esc(v53ConfidenceText(x.file))}
                    </span>

                    <span class="det-row-snr">
                        ${esc(fmt(x.snr_db," dB"))}
                    </span>

                    <span
                        class="v53-star ${v53IsFavorite(x.file) ? "on" : ""}"
                        data-star="${esc(x.file)}"
                        title="${v53IsFavorite(x.file) ? "Usuń z ulubionych" : "Dodaj do ulubionych"}">
                        ${v53IsFavorite(x.file) ? "★" : "☆"}
                    </span>

                </div>
                </div>
                <div class="det-row-meta">
                    czas: ${esc(fmt(x.duration_s," s"))} · częst.: ${esc(mhzText(x.frequency_hz))} · doppler: ${esc(fmt(x.doppler_hz," Hz"))}
                </div>
                <div class="det-row-file">${esc(x.file)}</div>
            </button>
        `;
    }).join("");

    /*
     * MR_SCORE_NO_FLICKER_RENDER_V1
     *
     * renderDetectionList przebudowuje detList przez innerHTML.
     * SNR/dB jest częścią bazowego HTML, score x/7 nie.
     *
     * Odtwarzamy score natychmiast po przebudowie DOM,
     * bez timera i bez MutationObserver.
     */
    if(
        typeof window.__mrScoreAfterRender
        ===
        "function"
    ){
        window.__mrScoreAfterRender();
    }


    document
        .querySelectorAll(".v53-star")
        .forEach(star=>{

            star.addEventListener(
                "click",
                ev=>{

                    ev.preventDefault();
                    ev.stopPropagation();

                    const file=
                        star.dataset.star;

                    v53ToggleFavorite(
                        file
                    );

                    renderDetectionList(
                        detectionsCache
                    );

                    v53UpdateFilterStatus();
                }
            );
        });


    document.querySelectorAll(".det-row").forEach(btn=>{
        btn.addEventListener("click", ()=>{
            selectedDetectionFile=btn.dataset.file;
            renderDetectionList(detectionsCache);
            const item=detectionsCache.find(x=>x.file===selectedDetectionFile) || null;
            renderDetectionDetail(item);
        });
    });

    const selected=
        detectionsCache.find(
            x=>x.file===selectedDetectionFile
        )
        ||
        null;

    if(selected){
        renderDetectionDetail(selected);
    }else{
        renderDetectionDetail(null);

        const placeholder=
            document.getElementById(
                "detPlaceholder"
            );

        if(placeholder){
            placeholder.textContent=
                "Kliknij detekcję po lewej, aby wygenerować szczegóły.";
        }
    }
}



function v5DrawHourly(
    rows
){

    const c=
        document.getElementById(
            "v5HourlyChart"
        );

    if(!c){
        return;
    }


    const ctx=
        c.getContext(
            "2d"
        );

    const w=c.width;
    const h=c.height;

    ctx.fillStyle="#070b0f";
    ctx.fillRect(
        0,
        0,
        w,
        h
    );


    if(
        !Array.isArray(
            rows
        )
        ||
        !rows.length
    ){
        return;
    }


    const max=
        Math.max(
            1,
            ...rows.map(
                x=>
                    Number(
                        x.count
                        ||
                        0
                    )
            )
        );


    const left=35;
    const right=10;
    const top=10;
    const bottom=30;

    const cw=
        w-left-right;

    const ch=
        h-top-bottom;

    const bw=
        cw
        /
        rows.length;


    ctx.strokeStyle="#293a47";
    ctx.lineWidth=1;

    ctx.beginPath();
    ctx.moveTo(
        left,
        top
    );
    ctx.lineTo(
        left,
        h-bottom
    );
    ctx.lineTo(
        w-right,
        h-bottom
    );
    ctx.stroke();


    rows.forEach(
        (row,i)=>{

            const value=
                Number(
                    row.count
                    ||
                    0
                );

            const bh=
                ch
                *
                value
                /
                max;

            const x=
                left
                +
                i*bw
                +
                2;

            const y=
                h
                -
                bottom
                -
                bh;


            ctx.fillStyle=
                "#4fb5d8";

            ctx.fillRect(
                x,
                y,
                Math.max(
                    2,
                    bw-4
                ),
                bh
            );


            if(
                i%3
                === 0
                ||
                i
                === rows.length-1
            ){

                ctx.fillStyle=
                    "#8494a2";

                ctx.font=
                    "10px sans-serif";

                ctx.textAlign=
                    "center";

                ctx.fillText(
                    row.label,
                    x
                    +
                    Math.max(
                        2,
                        bw-4
                    )
                    /2,
                    h-11
                );
            }
        }
    );


    ctx.fillStyle="#9baab6";
    ctx.textAlign="left";
    ctx.font="10px sans-serif";

    ctx.fillText(
        "max "+max+" / h",
        left+4,
        top+10
    );
}


async function refreshV5Stats(){

    try{

        const r=
            await fetch(
                "/api/stats?t="
                +
                Date.now(),
                {
                    cache:"no-store"
                }
            );


        const d=
            await r.json();


        if(!d.ok){
            return;
        }


        const a=
            d.last_24h
            ||
            {};

        const b=
            d.last_7d
            ||
            {};

        const c=
            d.last_30d
            ||
            {};


        document.getElementById(
            "v5Count24"
        ).textContent=
            a.count
            ??
            0;

        document.getElementById(
            "v5Rate24"
        ).textContent=
            "średnio "
            +
            Number(
                a.avg_per_hour
                ||
                0
            ).toFixed(
                2
            )
            +
            " / h";


        document.getElementById(
            "v5Count7"
        ).textContent=
            b.count
            ??
            0;

        document.getElementById(
            "v5Rate7"
        ).textContent=
            "średnio "
            +
            Number(
                b.avg_per_hour
                ||
                0
            ).toFixed(
                2
            )
            +
            " / h";


        document.getElementById(
            "v5Count30"
        ).textContent=
            c.count
            ??
            0;

        document.getElementById(
            "v5Rate30"
        ).textContent=
            "średnio "
            +
            Number(
                c.avg_per_hour
                ||
                0
            ).toFixed(
                2
            )
            +
            " / h";


        v5DrawHourly(
            d.hourly
            ||
            []
        );


    }catch(e){

        console.error(
            "stats:",
            e
        );
    }
}




/* MR_GLOBAL_SORT_PAGINATION_V1 */

const MR_GLOBAL_PAGE_SIZE = 8;

const MR_GLOBAL_FETCH_LIMIT = 5000;


function mrGlobalSortMode(){

    try{

        const sel=
            document.getElementById(
                "v55DetectionSort"
            );

        if(
            sel
            &&
            sel.value
        ){

            return sel.value;
        }

    }catch(_){
    }


    try{

        if(
            typeof v55SortMode
            !==
            "undefined"
        ){

            return (
                v55SortMode
                ||
                "newest"
            );
        }

    }catch(_){
    }


    return "newest";
}


function mrGlobalNeedsPiMeta(){

    return [
        "liked_first",
        "unliked_first",
        "score_desc",
        "score_asc"
    ].includes(
        mrGlobalSortMode()
    );
}


function mrGlobalSorter(){

    try{

        if(
            typeof window.v55SortData
            ===
            "function"
        ){

            return window.v55SortData;
        }

    }catch(_){
    }


    try{

        if(
            typeof v55SortData
            ===
            "function"
        ){

            return v55SortData;
        }

    }catch(_){
    }


    return null;
}


function mrRenderGlobalDetectionPage(){

    const all=
        Array.isArray(
            window.__mrGlobalDetectionsAll
        )
        ?
        window.__mrGlobalDetectionsAll
        :
        [];


    const sorter=
        mrGlobalSorter();


    let sorted=
        [...all];


    if(sorter){

        try{

            sorted=
                sorter(
                    sorted
                );

        }catch(error){

            console.error(
                "MR GLOBAL SORT:",
                error
            );
        }
    }


    if(
        !Array.isArray(
            sorted
        )
    ){

        sorted=
            [...all];
    }


    detectionTotalPages=
        Math.max(
            1,
            Math.ceil(
                sorted.length
                /
                MR_GLOBAL_PAGE_SIZE
            )
        );


    detectionPage=
        Math.min(
            Math.max(
                1,
                Number(
                    detectionPage
                    ||
                    1
                )
            ),
            detectionTotalPages
        );


    const start=
        (
            detectionPage
            -
            1
        )
        *
        MR_GLOBAL_PAGE_SIZE;


    detectionsCache=
        sorted.slice(
            start,
            start
            +
            MR_GLOBAL_PAGE_SIZE
        );


    renderDetectionList(
        detectionsCache
    );


    renderDetectionPager();


    console.log(
        "MR GLOBAL PAGE",
        {
            mode:
                mrGlobalSortMode(),

            page:
                detectionPage,

            pages:
                detectionTotalPages,

            all:
                all.length,

            shown:
                detectionsCache.length
        }
    );
}


window.mrRenderGlobalDetectionPage=
    mrRenderGlobalDetectionPage;


async function mrFetchAllDetections(){

    let page=1;

    let pages=1;

    let first=null;

    const byFile=
        new Map();


    do{

        const url=
            "/api/detections"
            +
            "?limit="
            +
            MR_GLOBAL_FETCH_LIMIT
            +
            "&page="
            +
            page
            +
            "&t="
            +
            Date.now();


        const response=
            await fetch(
                url,
                {
                    cache:"no-store"
                }
            );


        if(!response.ok){

            throw new Error(
                "HTTP "
                +
                response.status
                +
                " page="
                +
                page
            );
        }


        const data=
            await response.json();


        if(first === null){

            first=data;
        }


        const rows=
            Array.isArray(
                data.detections
            )
            ?
            data.detections
            :
            [];


        for(
            const item
            of rows
        ){

            const key=
                String(
                    item?.file
                    ??
                    item?.filename
                    ??
                    item?.name
                    ??
                    ""
                );


            if(key){

                byFile.set(
                    key,
                    item
                );

            }else{

                byFile.set(
                    "__row_"
                    +
                    page
                    +
                    "_"
                    +
                    byFile.size,
                    item
                );
            }
        }


        pages=
            Math.max(
                1,
                Number(
                    data.total_pages
                    ??
                    1
                )
            );


        if(pages > 100){

            throw new Error(
                "MR GLOBAL: "
                +
                "za dużo stron API: "
                +
                pages
            );
        }


        page++;


    }while(
        page <= pages
    );


    return {
        first:
            first
            ||
            {},

        detections:
            Array.from(
                byFile.values()
            )
    };
}


async function refreshDetections(
    force=false
){

    const mrNow=
        Date.now();


    const mrLast=
        Number(
            window.__mrLastDetectionRefresh
            ||
            0
        );


    /*
     * Automatyczne odświeżenie:
     * nadal maksymalnie raz na 5 minut.
     */

    if(
        !force
        &&
        mrLast
        &&
        (
            mrNow
            -
            mrLast
        )
        <
        300000
    ){

        return;
    }


    if(
        window.__mrDetectionRefreshBusy
    ){

        return;
    }


    window.__mrDetectionRefreshBusy=
        true;


    window.__mrLastDetectionRefresh=
        mrNow;


    try{

        /*
         * Dla ocen i ulubionych odświeżamy
         * metadata z Pi PRZED globalnym sortem.
         */

        if(
            typeof window.mrReloadSortMeta
            ===
            "function"
        ){

            try{

                await window.mrReloadSortMeta();

            }catch(error){

                console.warn(
                    "MR metadata:",
                    error
                );
            }
        }


        const result=
            await mrFetchAllDetections();


        const d=
            result.first;


        window.__mrGlobalDetectionsAll=
            result.detections;


        window.__mrGlobalDetectionsFetchedAt=
            Date.now();


        const today=
            Number(
                d.today_count
                ??
                0
            );


        const detCount=
            document.getElementById(
                "detCount"
            );


        if(detCount){

            detCount.textContent=
                today;
        }


        const todayBox=
            document.getElementById(
                "detectionsToday"
            );


        if(todayBox){

            todayBox.textContent=
                today;
        }


        mrRenderGlobalDetectionPage();


        console.log(
            "MR GLOBAL FETCH",
            {
                records:
                    window
                    .__mrGlobalDetectionsAll
                    .length,

                apiTotal:
                    d.total_items,

                apiPages:
                    d.total_pages,

                mode:
                    mrGlobalSortMode()
            }
        );


    }catch(error){

        console.error(
            "refreshDetections GLOBAL:",
            error
        );


    }finally{

        window.__mrDetectionRefreshBusy=
            false;
    }
}


document.getElementById(
    "detPrev"
).addEventListener(
    "click",
    async ()=>{
        if(
            detectionPage
            > 1
        ){
            detectionPage--;

            selectedDetectionFile=
                null;

            await refreshDetections(true);
        }
    }
);


document.getElementById(
    "detNext"
).addEventListener(
    "click",
    async ()=>{
        if(
            detectionPage
            < detectionTotalPages
        ){
            detectionPage++;

            selectedDetectionFile=
                null;

            await refreshDetections(true);
        }
    }
);



const v5MaxHold=
    document.getElementById(
        "maxHoldToggle"
    );


if(v5MaxHold){

    maxHoldEnabled=
        v5MaxHold.checked;

    v5MaxHold.addEventListener(
        "change",
        ()=>{

            maxHoldEnabled=
                v5MaxHold.checked;

            const item=
                detectionsCache.find(
                    x=>
                        x.file
                        ===
                        selectedDetectionFile
                );

            if(item){

                renderDetectionDetail(
                    item
                );
            }
        }
    );
}




// ============================================================
// V53_DETECTION_FILTERS_FAVORITES
// ============================================================

const V53_FAVORITES_KEY=
    "meteorradio-v53-favorites";

const V53_CLASS_KEY=
    "meteorradio-v56-classifications";


let v53AllDetections=[];
let v53FilteredDetections=[];
let v53FilterMode="all";

let v55SortMode="newest";


function v55Number(
    value,
    fallback=-Infinity
){

    const n=
        Number(
            value
        );

    return Number.isFinite(n)
        ? n
        : fallback;
}


function v55TimeValue(
    item
){

    const raw=
        String(
            item?.time
            ||
            ""
        );

    const t=
        Date.parse(
            raw.replace(
                " ",
                "T"
            )
        );

    return Number.isFinite(t)
        ? t
        : 0;
}


function v55SortData(
    data
){

    const out=[
        ...data
    ];


    if(
        v55SortMode
        ===
        "oldest"
    ){

        out.sort(
            (a,b)=>
                v55TimeValue(a)
                -
                v55TimeValue(b)
        );

        return out;
    }


    if(
        v55SortMode
        ===
        "confidence_desc"
    ){

        out.sort(
            (a,b)=>{

                const ca=
                    v53Confidence(
                        a.file
                    );

                const cb=
                    v53Confidence(
                        b.file
                    );

                const na=
                    ca===null
                    ? -Infinity
                    : ca;

                const nb=
                    cb===null
                    ? -Infinity
                    : cb;

                return (
                    nb
                    -
                    na
                )
                ||
                (
                    v55TimeValue(b)
                    -
                    v55TimeValue(a)
                );
            }
        );

        return out;
    }


    if(
        v55SortMode
        ===
        "confidence_asc"
    ){

        out.sort(
            (a,b)=>{

                const ca=
                    v53Confidence(
                        a.file
                    );

                const cb=
                    v53Confidence(
                        b.file
                    );


                /*
                 * Brak klasyfikacji zawsze
                 * na końcu.
                 */

                if(
                    ca===null
                    &&
                    cb===null
                ){
                    return (
                        v55TimeValue(b)
                        -
                        v55TimeValue(a)
                    );
                }

                if(ca===null){
                    return 1;
                }

                if(cb===null){
                    return -1;
                }


                return (
                    ca
                    -
                    cb
                )
                ||
                (
                    v55TimeValue(b)
                    -
                    v55TimeValue(a)
                );
            }
        );

        return out;
    }


    if(
        v55SortMode
        ===
        "snr_desc"
    ){

        out.sort(
            (a,b)=>
                (
                    v55Number(
                        b.snr_db
                    )
                    -
                    v55Number(
                        a.snr_db
                    )
                )
                ||
                (
                    v55TimeValue(b)
                    -
                    v55TimeValue(a)
                )
        );

        return out;
    }


    if(
        v55SortMode
        ===
        "duration_desc"
    ){

        out.sort(
            (a,b)=>
                (
                    v55Number(
                        b.duration_s
                    )
                    -
                    v55Number(
                        a.duration_s
                    )
                )
                ||
                (
                    v55TimeValue(b)
                    -
                    v55TimeValue(a)
                )
        );

        return out;
    }


    if(
        v55SortMode
        ===
        "favorites_first"
    ){

        out.sort(
            (a,b)=>{

                const fa=
                    v53IsFavorite(
                        a.file
                    )
                    ? 1
                    : 0;

                const fb=
                    v53IsFavorite(
                        b.file
                    )
                    ? 1
                    : 0;


                return (
                    fb
                    -
                    fa
                )
                ||
                (
                    v55TimeValue(b)
                    -
                    v55TimeValue(a)
                );
            }
        );

        return out;
    }


    /*
     * Domyślnie:
     * najnowsze pierwsze.
     */

    out.sort(
        (a,b)=>
            v55TimeValue(b)
            -
            v55TimeValue(a)
    );

    return out;
}


let v53FilterBusy=false;


function v53LoadObject(
    key,
    fallback
){

    try{

        const raw=
            localStorage.getItem(
                key
            );

        if(!raw){
            return fallback;
        }

        return JSON.parse(
            raw
        );

    }catch(e){

        return fallback;
    }
}


function v53SaveObject(
    key,
    value
){

    try{

        localStorage.setItem(
            key,
            JSON.stringify(
                value
            )
        );

    }catch(e){}
}


function v53Favorites(){

    const x=
        v53LoadObject(
            V53_FAVORITES_KEY,
            []
        );

    return Array.isArray(x)
        ? x
        : [];
}


function v53IsFavorite(
    file
){

    return v53Favorites()
        .includes(
            file
        );
}


function v53ToggleFavorite(
    file
){

    let fav=
        v53Favorites();

    if(
        fav.includes(
            file
        )
    ){

        fav=
            fav.filter(
                x=>x!==file
            );

    }else{

        fav.push(
            file
        );
    }


    v53SaveObject(
        V53_FAVORITES_KEY,
        fav
    );


    /*
     * Jeśli oglądamy tylko ulubione,
     * po odgwiazdkowaniu od razu
     * aktualizujemy listę.
     */

    if(
        v53FilterMode
        ===
        "fav"
    ){

        v53ApplyFilter();
    }
}


function v53Classifications(){

    const x=
        v53LoadObject(
            V53_CLASS_KEY,
            {}
        );

    return (
        x
        &&
        typeof x
        ===
        "object"
    )
        ? x
        : {};
}


function v53Confidence(
    file
){

    const c=
        v53Classifications()[
            file
        ];

    if(
        !c
        ||
        c.confidence
        ===
        undefined
        ||
        c.confidence
        ===
        null
    ){
        return null;
    }

    const x=
        Number(
            c.confidence
        );

    return Number.isFinite(x)
        ? x
        : null;
}



// V54_CONFIDENCE_DIRECT_COLOR_FIX
function v54ConfidenceClass(
    file
){

    const v=
        v53Confidence(
            file
        );

    if(v===null){
        return "";
    }

    if(v>=90){
        return "v54-conf-green";
    }

    if(v>=80){
        return "v54-conf-yellow";
    }

    if(v>=70){
        return "v54-conf-orange";
    }

    return "v54-conf-red";
}


function v53ConfidenceText(
    file
){

    const x=
        v53Confidence(
            file
        );

    return x===null
        ? ""
        : Math.round(x)+"%";
}


function v53DateText(
    value
){

    const s=
        String(
            value
            ||
            ""
        );


    /*
     * API zwraca:
     * 2026-09-17 23:21:08
     *
     * Pokazujemy:
     * 17.09.2026 · 23:21:08
     */

    const m=
        s.match(
            /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}:\d{2})/
        );


    if(!m){
        return s || "—";
    }


    return (
        m[3]
        + "."
        + m[2]
        + "."
        + m[1]
        + " · "
        + m[4]
    );
}


function v53SetStatus(
    text
){

    const el=
        document.getElementById(
            "v53FilterStatus"
        );

    if(el){
        el.textContent=
            text
            ||
            "";
    }
}


function v53UpdateFilterStatus(){

    const favCount=
        v53Favorites()
        .length;

    const sortLabels={
        newest:"najnowsze",
        oldest:"najstarsze",
        confidence_desc:"pewność ↓",
        confidence_asc:"pewność ↑",
        snr_desc:"SNR ↓",
        duration_desc:"czas ↓",
        favorites_first:"★ najpierw"
    };

    let text=
        "wyniki: "
        +
        v53FilteredDetections.length
        +
        " / "
        +
        v53AllDetections.length
        +
        " · "
        +
        (
            sortLabels[
                v55SortMode
            ]
            ||
            "najnowsze"
        );

    if(favCount){
        text+=
            " · ★ "
            +
            favCount;
    }

    v53SetStatus(
        text
    );
}


function v53SyncMaxHold(){

    const cb=
        document.getElementById(
            "maxHoldToggle"
        );

    const state=
        document.getElementById(
            "maxHoldState"
        );

    const wrap=
        document.getElementById(
            "v53MaxHoldWrap"
        );


    if(!cb){
        return;
    }


    if(state){

        state.textContent=
            cb.checked
            ? "ON"
            : "OFF";
    }


    if(wrap){

        wrap.classList.toggle(
            "on",
            cb.checked
        );
    }
}


async function v53FetchAllDetections(){

    let page=1;
    let pages=1;

    const all=[];

    let todayCount=null;


    do{

        const r=
            await fetch(
                "/api/detections"
                +
                "?limit=100"
                +
                "&page="
                +
                page
                +
                "&t="
                +
                Date.now()
            );


        if(!r.ok){
            throw new Error(
                "HTTP "
                +
                r.status
            );
        }


        const d=
            await r.json();


        if(
            todayCount
            ===
            null
        ){

            todayCount=
                d.today_count
                ??
                0;
        }


        const items=
            Array.isArray(
                d.detections
            )
                ? d.detections
                : [];


        all.push(
            ...items
        );


        pages=
            Math.max(
                1,
                Number(
                    d.total_pages
                    ||
                    1
                )
            );

        page++;

    }while(
        page
        <=
        pages
        &&
        page
        <=
        100
    );


    /*
     * Deduplikacja po nazwie SMP.
     */

    const map=
        new Map();

    for(
        const item
        of all
    ){

        if(
            item
            &&
            item.file
        ){

            map.set(
                item.file,
                item
            );
        }
    }


    v53AllDetections=
        Array.from(
            map.values()
        );


    document.getElementById(
        "detCount"
    ).textContent=
        todayCount
        ??
        v53AllDetections.length;
}


async function v53ClassifyMissing(){

    if(v53FilterBusy){
        return;
    }


    v53FilterBusy=true;


    const button=
        document.getElementById(
            "v53Recalc"
        );


    if(button){
        button.disabled=true;
    }


    try{

        let cache=
            v53Classifications();

        const missing=
            v53AllDetections
            .filter(
                x=>
                    x.file
                    &&
                    !cache[
                        x.file
                    ]
            );


        if(!missing.length){

            v53SetStatus(
                "pewność: cache gotowy"
            );

            return;
        }


        for(
            let i=0;
            i<missing.length;
            i++
        ){

            const item=
                missing[i];


            v53SetStatus(
                "analiza pewności "
                +
                (i+1)
                +
                " / "
                +
                missing.length
                +
                "…"
            );


            try{

                const r=
                    await fetch(
                        "/api/classification?file="
                        +
                        encodeURIComponent(
                            item.file
                        )
                        +
                        "&t="
                        +
                        Date.now()
                    );


                if(r.ok){

                    const d=
                        await r.json();


                    if(
                        d
                        &&
                        d.ok
                    ){

                        cache[
                            item.file
                        ]={
                            confidence:
                                Number(
                                    d.confidence
                                ),
                            kind:
                                d.kind
                                ||
                                "",
                            label:
                                d.label
                                ||
                                "",
                            ts:
                                Date.now()
                        };


                        v53SaveObject(
                            V53_CLASS_KEY,
                            cache
                        );
                    }
                }

            }catch(e){}


            /*
             * Nie odpalamy klasyfikatorów
             * lawinowo.
             */

            await new Promise(
                resolve=>
                    setTimeout(
                        resolve,
                        80
                    )
            );
        }

    }finally{

        v53FilterBusy=false;

        if(button){
            button.disabled=false;
        }
    }
}


function v53ApplyFilter(){

    let data=[
        ...v53AllDetections
    ];


    /*
     * FILTROWANIE
     *
     * Nie zmienia już kolejności.
     * Kolejność obsługuje wyłącznie
     * osobny dropdown "Sortuj".
     */

    if(
        v53FilterMode
        ===
        "fav"
    ){

        data=
            data.filter(
                x=>
                    v53IsFavorite(
                        x.file
                    )
            );

    }else if(
        [
            "60",
            "70",
            "80",
            "90"
        ].includes(
            v53FilterMode
        )
    ){

        const threshold=
            Number(
                v53FilterMode
            );


        data=
            data.filter(
                x=>{

                    const c=
                        v53Confidence(
                            x.file
                        );

                    return (
                        c!==null
                        &&
                        c>=threshold
                    );
                }
            );
    }


    /*
     * SORTOWANIE — niezależne od filtra.
     */

    data=
        v55SortData(
            data
        );


    v53FilteredDetections=
        data;


    detectionTotalPages=
        Math.max(
            1,
            Math.ceil(
                data.length
                /
                DETECTIONS_PER_PAGE
            )
        );


    detectionPage=
        Math.max(
            1,
            Math.min(
                detectionPage,
                detectionTotalPages
            )
        );


    const start=
        (
            detectionPage
            -
            1
        )
        *
        DETECTIONS_PER_PAGE;


    detectionsCache=
        data.slice(
            start,
            start
            +
            DETECTIONS_PER_PAGE
        );


    if(
        selectedDetectionFile
        &&
        !data.some(
            x=>
                x.file
                ===
                selectedDetectionFile
        )
    ){

        selectedDetectionFile=
            null;
    }


    renderDetectionList(
        detectionsCache
    );

    renderDetectionPager();

    v53UpdateFilterStatus();
}


async function v53RefreshDetections(
    classify=false
){

    try{

        await v53FetchAllDetections();


        if(classify){

            await v53ClassifyMissing();
        }


        v53ApplyFilter();

    }catch(e){

        console.error(
            "V5.3 refresh:",
            e
        );
    }
}


/*
 * Nadpisujemy stare pobieranie
 * stron backendowych.
 *
 * Backend zostaje nietknięty,
 * ale filtrujemy pełny indeks
 * po stronie przeglądarki.
 */

refreshDetections=
    async function(){

        await v53RefreshDetections(
            false
        );
    };


function v53InitControls(){

    const filter=
        document.getElementById(
            "v53DetectionFilter"
        );

    const sort=
        document.getElementById(
            "v55DetectionSort"
        );

    const recalc=
        document.getElementById(
            "v53Recalc"
        );

    const maxhold=
        document.getElementById(
            "maxHoldToggle"
        );


    if(filter){

        filter.addEventListener(
            "change",
            async ()=>{

                v53FilterMode=
                    filter.value;

                detectionPage=1;
                selectedDetectionFile=
                    null;


                const needsClass=
                    [
                        "60",
                        "70",
                        "80",
                        "90"
                    ].includes(
                        v53FilterMode
                    );


                await v53RefreshDetections(
                    needsClass
                );
            }
        );
    }


    if(sort){

        sort.addEventListener(
            "change",
            async ()=>{

                v55SortMode=
                    sort.value;

                detectionPage=1;


                const needsClass=
                    [
                        "confidence_desc",
                        "confidence_asc"
                    ].includes(
                        v55SortMode
                    );


                if(needsClass){

                    await v53FetchAllDetections();

                    await v53ClassifyMissing();
                }


                v53ApplyFilter();
            }
        );
    }


    if(recalc){

        recalc.addEventListener(
            "click",
            async ()=>{

                await v53FetchAllDetections();

                await v53ClassifyMissing();

                v53ApplyFilter();
            }
        );
    }


    if(maxhold){

        v53SyncMaxHold();

        maxhold.addEventListener(
            "change",
            v53SyncMaxHold
        );
    }
}


document.addEventListener(
    "DOMContentLoaded",
    v53InitControls
);



async function v5Start(){

    /* waterfall history disabled */
    /* refreshLive disabled */
    refreshHealth();
    refreshDetections();
    /* V511: statystyki dopiero po otwarciu modala */
}


v5Start();


// live polling disabled
// V511_ADAPTIVE_REFRESH_CACHE
//
// Nie robimy już wszystkich requestów jednocześnie.
//

setInterval(
    ()=>{
        if(!document.hidden){
            refreshHealth();
        }
    },
    10000
);


// Lista detekcji jest przesunięta o 5 s
// względem health — mniej burstów na 8094.

setTimeout(
    ()=>{

        if(!document.hidden){
            refreshDetections();
        }

        /* MR_REMOVE_LEGACY_10S_DETECTION_INTERVAL_V1 */
        /* Stary polling 10 s usunięty. */
        /* Refresh listy prowadzi timer 5-min. */
},
    5000
);


// Stare statystyki nie pracują w tle.
// Aktualizujemy je tylko kiedy modal jest otwarty.

setInterval(
    ()=>{

        if(document.hidden){
            return;
        }

        const modal=
            document.getElementById(
                "v59StatsModal"
            );

        if(
            modal
            &&
            modal.classList.contains(
                "open"
            )
        ){
            refreshV5Stats();
        }

    },
    60000
);


// Po powrocie do karty:
// health od razu,
// detekcje chwilę później.

document.addEventListener(
    "visibilitychange",
    ()=>{

        if(document.hidden){
            return;
        }

        refreshHealth();

        setTimeout(
            refreshDetections,
            2000
        );


        const modal=
            document.getElementById(
                "v59StatsModal"
            );

        if(
            modal
            &&
            modal.classList.contains(
                "open"
            )
        ){
            setTimeout(
                refreshV5Stats,
                3000
            );
        }
    }
);

// SCORE_LEFT_OF_DB_JS
function meteorradio_score_left_of_db_fix() {
  try {
    const rows = document.querySelectorAll(
      '.detection-row, .det-row, .detection-item, .det-item, .list-row, li, [data-detection-row]'
    );

    rows.forEach((row) => {
      let score = row.querySelector('.det-score, .score-badge, [data-score-badge], [data-score]');
      let snr   = row.querySelector('.det-snr, .snr-value, [data-snr]');

      if (!score || !snr) return;

      // jeśli score i dB są w tym samym kontenerze — wstaw score przed dB
      if (score.parentElement === snr.parentElement) {
        if (score.nextElementSibling !== snr) {
          snr.parentElement.insertBefore(score, snr);
        }
        return;
      }

      // jeśli są w różnych kontenerach — przenieś score do kontenera dB
      try {
        snr.parentElement.insertBefore(score, snr);
      } catch (e) {}
    });
  } catch (e) {}
}

window.addEventListener('load', function () {
  setTimeout(meteorradio_score_left_of_db_fix, 300);
  setTimeout(meteorradio_score_left_of_db_fix, 1200);
});


    /* SCORE_LEFT_OF_DB interval disabled */
    

</script>


<script>
// LIVE_WATERFALL_HARD_OFF_V2

(function(){

    function removeLiveUI(){

        document
        .querySelectorAll(
            "section.panel"
        )
        .forEach(
            section => {

                const title =
                    section.querySelector(
                        "h2.section-title"
                    );

                if(
                    title
                    &&
                    title.textContent
                    .trim()
                    .toUpperCase()
                    ===
                    "LIVE WATERFALL"
                ){
                    section.remove();
                }
            }
        );


        /*
         * Peak oraz SNR widma pochodziły
         * z wyłączonego live FFT.
         * Usuwamy ich karty, żeby nie
         * pokazywały starych danych.
         */

        ["peak","snr"].forEach(
            id => {

                const el =
                    document.getElementById(
                        id
                    );

                if(!el){
                    return;
                }


                let node = el;

                for(
                    let i=0;
                    i<5 && node;
                    i++
                ){

                    const cls =
                        String(
                            node.className
                            ||
                            ""
                        );


                    if(
                        /metric|card/i.test(
                            cls
                        )
                    ){
                        node.remove();
                        return;
                    }

                    node =
                        node.parentElement;
                }
            }
        );
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            removeLiveUI
        );

    }else{

        removeLiveUI();
    }

})();
</script>


<!-- V59_STATS_MODAL -->

<style>

/* ==========================================================
   V59 — STATYSTYKI W MODALU
   ========================================================== */

#v59StatsButton{
    appearance:none;
    -webkit-appearance:none;
    cursor:pointer;
    font-family:inherit;
    line-height:1;
    margin-right:8px;
    justify-content:center;
    text-align:center;
    white-space:nowrap;
    background:#263746;
    border-color:#465d70;
    color:#dce7ef;
}

#v59StatsButton:hover{
    background:#30485b;
    border-color:#5b7488;
}

#v59StatsButton:active{
    transform:translateY(1px);
}

#v59StatsModal{
    position:fixed;
    inset:0;
    z-index:10000;
    display:none;
    align-items:center;
    justify-content:center;
    padding:22px;
    background:rgba(0,0,0,.72);
    backdrop-filter:blur(3px);
    -webkit-backdrop-filter:blur(3px);
}

#v59StatsModal.open{
    display:flex;
}

#v59StatsDialog{
    position:relative;
    width:min(1220px,96vw);
    max-height:92vh;
    overflow:auto;

    background:#111c24;
    border:1px solid #405361;
    border-radius:9px;

    box-shadow:
        0 24px 70px rgba(0,0,0,.55);

    padding:14px;
}

#v59StatsClose{
    position:sticky;
    top:0;
    float:right;
    z-index:5;

    width:30px;
    height:30px;

    display:flex;
    align-items:center;
    justify-content:center;

    margin:0 0 6px 10px;

    border:1px solid #465d70;
    border-radius:6px;

    background:#182833;
    color:#dce7ef;

    font-size:20px;
    line-height:1;

    cursor:pointer;
}

#v59StatsClose:hover{
    background:#243a49;
}

#v59StatsHost{
    clear:both;
}

#v59StatsHost > section.panel{
    margin:0 !important;
    width:auto !important;
}

body.v59-modal-open{
    overflow:hidden;
}

@media(max-width:700px){

    #v59StatsModal{
        padding:8px;
    }

    #v59StatsDialog{
        width:98vw;
        max-height:96vh;
        padding:10px;
    }
}

</style>


<div
    id="v59StatsModal"
    aria-hidden="true">

    <div
        id="v59StatsDialog"
        role="dialog"
        aria-modal="true"
        aria-label="Statystyki detekcji">

        <button
            id="v59StatsClose"
            type="button"
            title="Zamknij"
            aria-label="Zamknij">
            ×
        </button>

        <div id="v59StatsHost"></div>

    </div>

</div>


<script>

(function(){

    "use strict";


    function v59FindStatsSection(){

        const panels=[
            ...document.querySelectorAll(
                "section.panel"
            )
        ];


        return panels.find(
            panel =>
                (
                    panel.textContent
                    ||
                    ""
                )
                .toUpperCase()
                .includes(
                    "STATYSTYKI DETEKCJI"
                )
        ) || null;
    }


    function v59SyncButtonSize(){

        const badge=
            document.getElementById(
                "liveBadge"
            );

        const button=
            document.getElementById(
                "v59StatsButton"
            );


        if(
            !badge
            ||
            !button
        ){
            return;
        }


        const rect=
            badge.getBoundingClientRect();


        if(rect.width > 0){

            button.style.width=
                rect.width
                +
                "px";

            button.style.minWidth=
                rect.width
                +
                "px";

            button.style.maxWidth=
                rect.width
                +
                "px";
        }


        if(rect.height > 0){

            button.style.height=
                rect.height
                +
                "px";

            button.style.minHeight=
                rect.height
                +
                "px";
        }


        /*
         * STATYSTYKA jest dłuższa niż NASŁUCH,
         * więc minimalnie zmniejszamy font,
         * zachowując IDENTYCZNY rozmiar przycisku.
         */
        button.style.fontSize="9px";
        button.style.fontWeight="700";
        button.style.letterSpacing=".15px";
    }


    function v59Open(){

        const modal=
            document.getElementById(
                "v59StatsModal"
            );


        if(!modal){
            return;
        }


        modal.classList.add(
            "open"
        );

        modal.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.classList.add(
            "v59-modal-open"
        );


        /*
         * Statystyki mogły być odświeżane,
         * kiedy modal był niewidoczny.
         * Po otwarciu prosimy istniejący V5
         * o ponowne przeliczenie / redraw.
         */
        requestAnimationFrame(
            () => {

                if(
                    typeof refreshV5Stats
                    ===
                    "function"
                ){

                    try{
                        refreshV5Stats();
                    }catch(e){}
                }
            }
        );
    }


    function v59Close(){

        const modal=
            document.getElementById(
                "v59StatsModal"
            );


        if(!modal){
            return;
        }


        modal.classList.remove(
            "open"
        );

        modal.setAttribute(
            "aria-hidden",
            "true"
        );

        document.body.classList.remove(
            "v59-modal-open"
        );
    }


    function v59Init(){

        const badge=
            document.getElementById(
                "liveBadge"
            );

        const modal=
            document.getElementById(
                "v59StatsModal"
            );

        const host=
            document.getElementById(
                "v59StatsHost"
            );

        const close=
            document.getElementById(
                "v59StatsClose"
            );

        const stats=
            v59FindStatsSection();


        if(!badge){
            console.error(
                "V59: brak liveBadge"
            );
            return;
        }


        if(!stats){
            console.error(
                "V59: brak sekcji STATYSTYKI DETEKCJI"
            );
            return;
        }


        if(
            !modal
            ||
            !host
            ||
            !close
        ){
            console.error(
                "V59: brak elementów modala"
            );
            return;
        }


        /*
         * PRZENOSIMY istniejącą sekcję.
         *
         * appendChild nie kopiuje jej —
         * fizycznie usuwa ją ze starego
         * miejsca na głównej stronie.
         */
        host.appendChild(
            stats
        );


        /*
         * Przycisk dokładnie po LEWEJ
         * stronie badge NASŁUCH.
         */
        const button=
            document.createElement(
                "button"
            );


        button.id=
            "v59StatsButton";

        button.type=
            "button";

        /*
         * Używamy tej samej klasy badge,
         * aby zachować identyczną geometrię.
         */
        button.className=
            "badge";

        button.textContent=
            "STATYSTYKA";

        button.title=
            "Otwórz statystyki detekcji";


        badge.parentNode.insertBefore(
            button,
            badge
        );


        v59SyncButtonSize();


        button.addEventListener(
            "click",
            v59Open
        );


        close.addEventListener(
            "click",
            v59Close
        );


        modal.addEventListener(
            "click",
            event => {

                if(
                    event.target
                    ===
                    modal
                ){
                    v59Close();
                }
            }
        );


        document.addEventListener(
            "keydown",
            event => {

                if(
                    event.key
                    ===
                    "Escape"
                ){
                    v59Close();
                }
            }
        );


        window.addEventListener(
            "resize",
            v59SyncButtonSize
        );


        console.log(
            "V59_STATS_MODAL ready"
        );
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            v59Init,
            {
                once:true
            }
        );

    }else{

        v59Init();
    }

})();

</script>


<!-- V591_STATS_NEXT_TO_LISTEN -->

<style>

#v591TopActions{
    margin-left:auto;
    display:flex;
    align-items:center;
    justify-content:flex-end;
    gap:8px;
    flex:0 0 auto;
}

#v591TopActions #v59StatsButton{
    margin:0 !important;
}

</style>

<script>

(function(){

    function v591Group(){

        const stats =
            document.getElementById(
                "v59StatsButton"
            );

        const listen =
            document.getElementById(
                "liveBadge"
            );

        if(!stats || !listen){
            return false;
        }

        if(
            document.getElementById(
                "v591TopActions"
            )
        ){
            return true;
        }

        const parent =
            listen.parentNode;

        const group =
            document.createElement(
                "div"
            );

        group.id =
            "v591TopActions";

        parent.insertBefore(
            group,
            stats
        );

        group.appendChild(
            stats
        );

        group.appendChild(
            listen
        );

        return true;
    }


    function v591Start(){

        let tries = 0;

        const timer =
            setInterval(
                () => {

                    tries++;

                    if(
                        v591Group()
                        ||
                        tries >= 30
                    ){
                        clearInterval(
                            timer
                        );
                    }

                },
                50
            );
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            v591Start,
            {once:true}
        );

    }else{

        v591Start();
    }

})();

</script>


<!-- V510_THREE_STATS_CHARTS -->

<style>

/* ==========================================================
   V5.10 — trzy wykresy statystyk
   ========================================================== */

#v510StatsDashboard{
    width:100%;
    box-sizing:border-box;
}

#v510StatsHeader{
    margin:2px 0 12px 0;
}

#v510StatsHeader h2{
    margin:0 0 4px 0;
    font-size:14px;
    color:#e3edf4;
}

#v510StatsHeader div{
    font-size:11px;
    color:#91a5b4;
}

.v510-chart-box{
    background:#091119;
    border:1px solid #304654;
    border-radius:6px;
    padding:10px 12px 8px 12px;
    margin-bottom:12px;
}

.v510-chart-head{
    display:flex;
    justify-content:space-between;
    align-items:flex-end;
    gap:12px;
    margin-bottom:7px;
}

.v510-chart-title{
    font-size:12px;
    font-weight:700;
    color:#dce8ef;
}

.v510-chart-summary{
    font-size:11px;
    color:#8fa4b4;
    white-space:nowrap;
}

.v510-chart-canvas{
    display:block;
    width:100%;
    height:165px;
}

#v510StatsLoading{
    padding:40px 10px;
    text-align:center;
    color:#91a5b4;
    font-size:12px;
}

@media(max-width:700px){

    .v510-chart-canvas{
        height:145px;
    }

    .v510-chart-head{
        align-items:flex-start;
        flex-direction:column;
        gap:3px;
    }
}

</style>


<script>

(function(){

    "use strict";


    // ========================================================
    // DATE PARSER
    // API zwraca np.:
    // 2026-09-18 00:36:20
    // ========================================================

    function v510ParseDate(value){

        if(!value){
            return null;
        }

        const m=
            String(value).match(
                /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/
            );

        if(!m){
            return null;
        }

        const d=
            new Date(
                Number(m[1]),
                Number(m[2])-1,
                Number(m[3]),
                Number(m[4]),
                Number(m[5]),
                Number(m[6])
            );

        if(
            Number.isNaN(
                d.getTime()
            )
        ){
            return null;
        }

        return d;
    }


    function v510Pad(value){

        return String(
            value
        ).padStart(
            2,
            "0"
        );
    }


    function v510HHMM(date){

        return (
            v510Pad(
                date.getHours()
            )
            +
            ":"
            +
            v510Pad(
                date.getMinutes()
            )
        );
    }


    function v510Day(date){

        return (
            v510Pad(
                date.getDate()
            )
            +
            "."
            +
            v510Pad(
                date.getMonth()+1
            )
        );
    }


    // ========================================================
    // POBIERZ CAŁĄ HISTORIĘ DETEKCJI
    // Backend ma 8 / stronę.
    // ========================================================

    async function v510FetchAllDetections(){

        const firstResponse=
            await fetch(
                "/api/detections?page=1&limit=8&t="
                +
                Date.now(),
                {
                    cache:"no-store"
                }
            );

        if(!firstResponse.ok){

            throw new Error(
                "HTTP "
                +
                firstResponse.status
            );
        }


        const first=
            await firstResponse.json();


        const pages=
            Math.max(
                1,
                Number(
                    first.total_pages
                    ||
                    1
                )
            );


        const all=[
            ...(
                first.detections
                ||
                []
            )
        ];


        for(
            let page=2;
            page<=pages;
            page++
        ){

            const response=
                await fetch(
                    "/api/detections?page="
                    +
                    page
                    +
                    "&limit=8&t="
                    +
                    Date.now(),
                    {
                        cache:"no-store"
                    }
                );


            if(!response.ok){
                continue;
            }


            const data=
                await response.json();


            all.push(
                ...(
                    data.detections
                    ||
                    []
                )
            );
        }


        //
        // deduplikacja po nazwie SMP
        //
        const unique=
            new Map();


        for(const item of all){

            const key=
                item.file
                ||
                (
                    item.time
                    +
                    "|"
                    +
                    item.frequency_hz
                );

            unique.set(
                key,
                item
            );
        }


        return [
            ...unique.values()
        ];
    }


    // ========================================================
    // BINY — OSTATNIA GODZINA
    // 12 x 5 min
    // ========================================================

    function v510Bins1h(
        dates,
        now
    ){

        const span=
            60
            *
            60
            *
            1000;

        const width=
            5
            *
            60
            *
            1000;

        const start=
            new Date(
                now.getTime()
                -
                span
            );


        const bins=
            Array(12).fill(0);

        const labels=[];


        for(let i=0;i<12;i++){

            labels.push(
                v510HHMM(
                    new Date(
                        start.getTime()
                        +
                        i*width
                    )
                )
            );
        }


        for(const d of dates){

            const age=
                d.getTime()
                -
                start.getTime();


            if(
                age < 0
                ||
                d > now
            ){
                continue;
            }


            let index=
                Math.floor(
                    age
                    /
                    width
                );


            if(index === 12){
                index=11;
            }


            if(
                index >= 0
                &&
                index < 12
            ){
                bins[index]++;
            }
        }


        return {
            bins,
            labels,
            total:
                bins.reduce(
                    (a,b)=>a+b,
                    0
                ),
            unit:"5 min"
        };
    }


    // ========================================================
    // BINY — OSTATNIE 24H
    // 24 x 1 h
    // ========================================================

    function v510Bins24h(
        dates,
        now
    ){

        const span=
            24
            *
            60
            *
            60
            *
            1000;

        const width=
            60
            *
            60
            *
            1000;

        const start=
            new Date(
                now.getTime()
                -
                span
            );


        const bins=
            Array(24).fill(0);

        const labels=[];


        for(let i=0;i<24;i++){

            const d=
                new Date(
                    start.getTime()
                    +
                    i*width
                );


            labels.push(
                v510Pad(
                    d.getHours()
                )
            );
        }


        for(const d of dates){

            const delta=
                d.getTime()
                -
                start.getTime();


            if(
                delta < 0
                ||
                d > now
            ){
                continue;
            }


            let index=
                Math.floor(
                    delta
                    /
                    width
                );


            if(index === 24){
                index=23;
            }


            if(
                index >= 0
                &&
                index < 24
            ){
                bins[index]++;
            }
        }


        return {
            bins,
            labels,
            total:
                bins.reduce(
                    (a,b)=>a+b,
                    0
                ),
            unit:"h"
        };
    }


    // ========================================================
    // BINY — OSTATNIE 7 DNI
    // dziś + poprzednie 6 dni
    // ========================================================

    function v510Bins7d(
        dates,
        now
    ){

        const start=
            new Date(
                now.getFullYear(),
                now.getMonth(),
                now.getDate(),
                0,0,0,0
            );


        start.setDate(
            start.getDate()-6
        );


        const bins=
            Array(7).fill(0);

        const labels=[];


        for(let i=0;i<7;i++){

            const d=
                new Date(
                    start
                );

            d.setDate(
                d.getDate()+i
            );

            labels.push(
                v510Day(d)
            );
        }


        for(const d of dates){

            if(
                d < start
                ||
                d > now
            ){
                continue;
            }


            const day=
                new Date(
                    d.getFullYear(),
                    d.getMonth(),
                    d.getDate(),
                    0,0,0,0
                );


            const index=
                Math.round(
                    (
                        day.getTime()
                        -
                        start.getTime()
                    )
                    /
                    (
                        24
                        *
                        60
                        *
                        60
                        *
                        1000
                    )
                );


            if(
                index >= 0
                &&
                index < 7
            ){
                bins[index]++;
            }
        }


        return {
            bins,
            labels,
            total:
                bins.reduce(
                    (a,b)=>a+b,
                    0
                ),
            unit:"dzień"
        };
    }


    // ========================================================
    // CANVAS
    // ========================================================

    function v510Draw(
        canvas,
        data,
        labelEvery
    ){

        if(!canvas){
            return;
        }


        const rect=
            canvas.getBoundingClientRect();


        const cssWidth=
            Math.max(
                300,
                Math.round(
                    rect.width
                    ||
                    900
                )
            );


        const cssHeight=
            Math.max(
                140,
                Math.round(
                    rect.height
                    ||
                    165
                )
            );


        const dpr=
            Math.max(
                1,
                window.devicePixelRatio
                ||
                1
            );


        canvas.width=
            Math.round(
                cssWidth*dpr
            );

        canvas.height=
            Math.round(
                cssHeight*dpr
            );


        const ctx=
            canvas.getContext(
                "2d"
            );


        ctx.setTransform(
            dpr,
            0,
            0,
            dpr,
            0,
            0
        );


        ctx.clearRect(
            0,
            0,
            cssWidth,
            cssHeight
        );


        const left=34;
        const right=8;
        const top=14;
        const bottom=27;


        const w=
            cssWidth
            -
            left
            -
            right;

        const h=
            cssHeight
            -
            top
            -
            bottom;


        const maxValue=
            Math.max(
                1,
                ...data.bins
            );


        // osie

        ctx.strokeStyle=
            "#283b48";

        ctx.lineWidth=1;

        ctx.beginPath();

        ctx.moveTo(
            left,
            top
        );

        ctx.lineTo(
            left,
            top+h
        );

        ctx.lineTo(
            left+w,
            top+h
        );

        ctx.stroke();


        // delikatne linie 25 / 50 / 75 / 100%

        ctx.strokeStyle=
            "#172731";

        for(
            let i=1;
            i<=4;
            i++
        ){

            const y=
                top
                +
                h
                -
                h*i/4;

            ctx.beginPath();

            ctx.moveTo(
                left,
                y
            );

            ctx.lineTo(
                left+w,
                y
            );

            ctx.stroke();
        }


        const count=
            data.bins.length;

        const slot=
            w/count;

        const barWidth=
            Math.max(
                2,
                slot*0.78
            );


        for(
            let i=0;
            i<count;
            i++
        ){

            const value=
                data.bins[i];

            const barHeight=
                (
                    value
                    /
                    maxValue
                )
                *
                h;


            const x=
                left
                +
                i*slot
                +
                (
                    slot
                    -
                    barWidth
                )/2;


            const y=
                top
                +
                h
                -
                barHeight;


            ctx.fillStyle=
                "#55b7d8";

            ctx.fillRect(
                x,
                y,
                barWidth,
                barHeight
            );


            //
            // wartość nad słupkiem,
            // tylko gdy > 0
            //
            if(value > 0){

                ctx.fillStyle=
                    "#bed1dc";

                ctx.font=
                    "9px sans-serif";

                ctx.textAlign=
                    "center";

                ctx.fillText(
                    String(value),
                    x+barWidth/2,
                    Math.max(
                        top+9,
                        y-3
                    )
                );
            }


            //
            // etykiety osi X
            //
            if(
                i % labelEvery
                ===
                0
                ||
                i === count-1
            ){

                ctx.fillStyle=
                    "#8095a4";

                ctx.font=
                    "9px sans-serif";

                ctx.textAlign=
                    "center";

                ctx.fillText(
                    data.labels[i],
                    left
                    +
                    i*slot
                    +
                    slot/2,
                    cssHeight-8
                );
            }
        }


        // max po lewej

        ctx.fillStyle=
            "#92a7b6";

        ctx.font=
            "9px sans-serif";

        ctx.textAlign=
            "left";

        ctx.fillText(
            "max "
            +
            maxValue,
            3,
            top+8
        );
    }


    // ========================================================
    // HTML
    // ========================================================

    function v510Build(){

        const host=
            document.getElementById(
                "v59StatsHost"
            );


        if(!host){
            return false;
        }


        if(
            document.getElementById(
                "v510StatsDashboard"
            )
        ){
            return true;
        }


        //
        // Stara sekcja V5 zostaje w DOM,
        // żeby refreshV5Stats() mógł działać,
        // ale nie pokazujemy jej.
        //
        const oldStats=
            host.querySelector(
                "section.panel"
            );


        if(oldStats){

            oldStats.style.display=
                "none";
        }


        const dashboard=
            document.createElement(
                "div"
            );


        dashboard.id=
            "v510StatsDashboard";


        dashboard.innerHTML=`
            <div id="v510StatsHeader">
                <h2>STATYSTYKI DETEKCJI</h2>
                <div>
                    histogram liczby zapisanych detekcji MeteorRadio
                </div>
            </div>

            <div id="v510StatsLoading">
                Ładowanie statystyk…
            </div>

            <div
                id="v510Charts"
                style="display:none">

                <div class="v510-chart-box">
                    <div class="v510-chart-head">
                        <div class="v510-chart-title">
                            OSTATNIA GODZINA
                        </div>
                        <div
                            id="v510Sum1h"
                            class="v510-chart-summary">
                        </div>
                    </div>

                    <canvas
                        id="v510Chart1h"
                        class="v510-chart-canvas">
                    </canvas>
                </div>

                <div class="v510-chart-box">
                    <div class="v510-chart-head">
                        <div class="v510-chart-title">
                            OSTATNIE 24 GODZINY
                        </div>
                        <div
                            id="v510Sum24h"
                            class="v510-chart-summary">
                        </div>
                    </div>

                    <canvas
                        id="v510Chart24h"
                        class="v510-chart-canvas">
                    </canvas>
                </div>

                <div class="v510-chart-box">
                    <div class="v510-chart-head">
                        <div class="v510-chart-title">
                            OSTATNIE 7 DNI
                        </div>
                        <div
                            id="v510Sum7d"
                            class="v510-chart-summary">
                        </div>
                    </div>

                    <canvas
                        id="v510Chart7d"
                        class="v510-chart-canvas">
                    </canvas>
                </div>

            </div>
        `;


        host.insertBefore(
            dashboard,
            host.firstChild
        );


        return true;
    }


    async function v510Refresh(){

        if(
            !v510Build()
        ){
            return;
        }


        const loading=
            document.getElementById(
                "v510StatsLoading"
            );

        const charts=
            document.getElementById(
                "v510Charts"
            );


        loading.style.display=
            "block";

        loading.textContent=
            "Ładowanie statystyk…";


        try{

            const items=
                await v510FetchAllDetections();


            const dates=
                items
                .map(
                    item =>
                        v510ParseDate(
                            item.time
                        )
                )
                .filter(
                    Boolean
                );


            const now=
                new Date();


            const h1=
                v510Bins1h(
                    dates,
                    now
                );

            const h24=
                v510Bins24h(
                    dates,
                    now
                );

            const d7=
                v510Bins7d(
                    dates,
                    now
                );


            charts.style.display=
                "block";

            loading.style.display=
                "none";


            document.getElementById(
                "v510Sum1h"
            ).textContent=
                h1.total
                +
                " detekcji · 5 min / słupek";


            document.getElementById(
                "v510Sum24h"
            ).textContent=
                h24.total
                +
                " detekcji · 1 h / słupek";


            document.getElementById(
                "v510Sum7d"
            ).textContent=
                d7.total
                +
                " detekcji · 1 dzień / słupek";


            //
            // modal musi być już widoczny,
            // zanim pobierzemy jego szerokość.
            //
            requestAnimationFrame(
                () => {

                    v510Draw(
                        document.getElementById(
                            "v510Chart1h"
                        ),
                        h1,
                        2
                    );


                    v510Draw(
                        document.getElementById(
                            "v510Chart24h"
                        ),
                        h24,
                        3
                    );


                    v510Draw(
                        document.getElementById(
                            "v510Chart7d"
                        ),
                        d7,
                        1
                    );
                }
            );

        }catch(error){

            console.error(
                "V5.10 stats:",
                error
            );

            loading.style.display=
                "block";

            loading.textContent=
                "Nie udało się pobrać statystyk.";

            charts.style.display=
                "none";
        }
    }


    // ========================================================
    // START
    // Przycisk STATYSTYKA jest tworzony dynamicznie przez V5.9.
    // ========================================================

    function v510Start(){

        let tries=0;


        const timer=
            setInterval(
                () => {

                    tries++;


                    const button=
                        document.getElementById(
                            "v59StatsButton"
                        );


                    if(button){

                        clearInterval(
                            timer
                        );


                        v510Build();


                        button.addEventListener(
                            "click",
                            () => {

                                //
                                // V5.9 najpierw otwiera modal.
                                // Krótki timeout gwarantuje,
                                // że canvas ma już realną szerokość.
                                //
                                setTimeout(
                                    v510Refresh,
                                    30
                                );
                            }
                        );


                        return;
                    }


                    if(tries >= 50){

                        clearInterval(
                            timer
                        );
                    }

                },
                50
            );
    }


    window.addEventListener(
        "resize",
        () => {

            const modal=
                document.getElementById(
                    "v59StatsModal"
                );


            if(
                modal
                &&
                modal.classList.contains(
                    "open"
                )
            ){

                setTimeout(
                    v510Refresh,
                    80
                );
            }
        }
    );


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            v510Start,
            {
                once:true
            }
        );

    }else{

        v510Start();
    }

})();

</script>


<!-- V5101_RESTORE_TOP_STATS_CARDS -->

<style>

/*
 * V5.10.1
 *
 * Nagłówek zapewnia stara sekcja V5,
 * więc nie dublujemy go nad nowymi wykresami.
 */
#v510StatsHeader{
    display:none !important;
}


/*
 * Trzy oryginalne kafle zostają widoczne.
 */
#v59StatsHost > section.panel{
    display:block;
}


/*
 * Stary pojedynczy wykres V5
 * ukrywamy — zastępują go trzy nowe.
 */
#v5HourlyChart{
    display:none !important;
}

</style>


<script>

(function(){

    "use strict";


    function v5101Restore(){

        const host=
            document.getElementById(
                "v59StatsHost"
            );

        const dashboard=
            document.getElementById(
                "v510StatsDashboard"
            );

        const oldStats=
            host
            ?
            host.querySelector(
                "section.panel"
            )
            :
            null;


        if(
            !host
            ||
            !dashboard
            ||
            !oldStats
        ){
            return false;
        }


        /*
         * V5.10 wcześniej schował
         * całą starą sekcję.
         * Przywracamy ją.
         */
        oldStats.style.display=
            "block";


        /*
         * Trzy stare kafle mają być NAD
         * naszymi trzema nowymi wykresami.
         */
        if(
            oldStats.nextSibling
            !==
            dashboard
        ){

            host.insertBefore(
                oldStats,
                dashboard
            );
        }


        /*
         * Ukrywamy WYŁĄCZNIE stary wykres.
         */
        const oldChart=
            document.getElementById(
                "v5HourlyChart"
            );


        if(oldChart){

            const parent=
                oldChart.parentElement;


            /*
             * Zwykle canvas siedzi we własnym
             * obramowanym kontenerze.
             * Chowamy kontener, ale nigdy
             * całej sekcji z kaflami.
             */
            if(
                parent
                &&
                parent !== oldStats
                &&
                !parent.contains(
                    document.getElementById(
                        "v5Count24"
                    )
                )
            ){

                parent.style.display=
                    "none";

            }else{

                oldChart.style.display=
                    "none";
            }
        }


        /*
         * Nowy nagłówek jest zbędny,
         * bo nagłówek starej sekcji
         * pozostaje na górze.
         */
        const newHeader=
            document.getElementById(
                "v510StatsHeader"
            );


        if(newHeader){

            newHeader.style.display=
                "none";
        }


        return true;
    }


    function v5101Start(){

        let tries=0;


        const timer=
            setInterval(
                () => {

                    tries++;


                    if(
                        v5101Restore()
                        ||
                        tries >= 60
                    ){

                        clearInterval(
                            timer
                        );
                    }

                },
                50
            );
    }


    /*
     * Ponawiamy również przy otwarciu
     * modala STATYSTYKA.
     */
    document.addEventListener(
        "click",
        event => {

            const button=
                event.target.closest
                ?
                event.target.closest(
                    "#v59StatsButton"
                )
                :
                null;


            if(button){

                setTimeout(
                    v5101Restore,
                    60
                );
            }
        }
    );


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            v5101Start,
            {
                once:true
            }
        );

    }else{

        v5101Start();
    }

})();

</script>


<!-- V5102_FIXED_FRONTEND_ONLY -->

<style>

/*
 * V5.10.2 FIX
 * 4 kafle w jednym rzędzie
 */

#v5102Card1h{
    min-width:0;
}


/*
 * 30-dniowy wykres korzysta z wyglądu
 * istniejących wykresów V5.10.
 */

#v5102Chart30d{
    width:100%;
    height:165px;
    display:block;
}

</style>


<script>

(function(){

    "use strict";


    // ========================================================
    // DATA
    // ========================================================

    function v5102ParseDate(value){

        if(!value){
            return null;
        }


        const m=
            String(value).match(
                /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/
            );


        if(!m){
            return null;
        }


        const d=
            new Date(
                Number(m[1]),
                Number(m[2])-1,
                Number(m[3]),
                Number(m[4]),
                Number(m[5]),
                Number(m[6])
            );


        return Number.isNaN(
            d.getTime()
        )
        ?
        null
        :
        d;
    }


    function v5102Pad(value){

        return String(
            value
        ).padStart(
            2,
            "0"
        );
    }


    function v5102DayLabel(date){

        return (
            v5102Pad(
                date.getDate()
            )
            +
            "."
            +
            v5102Pad(
                date.getMonth()+1
            )
        );
    }


    async function v5102FetchAll(){

        const firstResponse=
            await fetch(
                "/api/detections?page=1&limit=8&t="
                +
                Date.now(),
                {
                    cache:"no-store"
                }
            );


        if(!firstResponse.ok){

            throw new Error(
                "HTTP "
                +
                firstResponse.status
            );
        }


        const first=
            await firstResponse.json();


        const pages=
            Math.max(
                1,
                Number(
                    first.total_pages
                    ||
                    1
                )
            );


        const all=[
            ...(
                first.detections
                ||
                []
            )
        ];


        for(
            let page=2;
            page<=pages;
            page++
        ){

            const response=
                await fetch(
                    "/api/detections?page="
                    +
                    page
                    +
                    "&limit=8&t="
                    +
                    Date.now(),
                    {
                        cache:"no-store"
                    }
                );


            if(!response.ok){
                continue;
            }


            const data=
                await response.json();


            all.push(
                ...(
                    data.detections
                    ||
                    []
                )
            );
        }


        /*
         * Usuwamy duplikaty.
         */
        const unique=
            new Map();


        for(const item of all){

            const key=
                item.file
                ||
                (
                    item.time
                    +
                    "|"
                    +
                    item.frequency_hz
                );


            unique.set(
                key,
                item
            );
        }


        return [
            ...unique.values()
        ];
    }


    // ========================================================
    // OSTATNIA GODZINA
    // ========================================================

    function v5102OneHour(
        dates,
        now
    ){

        const start=
            new Date(
                now.getTime()
                -
                60
                *
                60
                *
                1000
            );


        const count=
            dates.filter(
                d =>
                    d >= start
                    &&
                    d <= now
            ).length;


        return {
            count:count
        };
    }


    // ========================================================
    // OSTATNIE 30 DNI
    // 30 x 1 dzień
    // ========================================================

    function v5102ThirtyDays(
        dates,
        now
    ){

        const today=
            new Date(
                now.getFullYear(),
                now.getMonth(),
                now.getDate(),
                0,0,0,0
            );


        const start=
            new Date(
                today
            );


        start.setDate(
            start.getDate()-29
        );


        const bins=
            Array(30).fill(0);

        const labels=[];


        for(
            let i=0;
            i<30;
            i++
        ){

            const d=
                new Date(
                    start
                );


            d.setDate(
                d.getDate()+i
            );


            labels.push(
                v5102DayLabel(
                    d
                )
            );
        }


        for(const d of dates){

            if(
                d < start
                ||
                d > now
            ){
                continue;
            }


            const day=
                new Date(
                    d.getFullYear(),
                    d.getMonth(),
                    d.getDate(),
                    0,0,0,0
                );


            const delta=
                Math.round(
                    (
                        day
                        -
                        start
                    )
                    /
                    (
                        24
                        *
                        60
                        *
                        60
                        *
                        1000
                    )
                );


            if(
                delta >= 0
                &&
                delta < 30
            ){

                bins[
                    delta
                ]++;
            }
        }


        return {
            bins:bins,

            labels:labels,

            total:
                bins.reduce(
                    (a,b)=>a+b,
                    0
                )
        };
    }


    // ========================================================
    // KAFEL 1H
    // ========================================================

    function v5102FindStatsGrid(){

        const count24=
            document.getElementById(
                "v5Count24"
            );


        if(!count24){
            return null;
        }


        const labels=[
            "OSTATNIE 24 H",
            "OSTATNIE 7 DNI",
            "OSTATNIE 30 DNI"
        ];


        let node=count24;


        for(
            let level=0;
            level<7
            &&
            node;
            level++
        ){

            const parent=
                node.parentElement;


            if(!parent){
                break;
            }


            const children=[
                ...parent.children
            ];


            const hits=
                children.filter(
                    child => {

                        const text=
                            (
                                child.innerText
                                ||
                                ""
                            )
                            .replace(
                                /\s+/g,
                                " "
                            )
                            .toUpperCase();


                        return labels.some(
                            label =>
                                text.includes(
                                    label
                                )
                        );
                    }
                );


            if(hits.length >= 3){

                return {
                    grid:parent,

                    card24:
                        hits.find(
                            child =>
                                (
                                    child.innerText
                                    ||
                                    ""
                                )
                                .toUpperCase()
                                .includes(
                                    "OSTATNIE 24 H"
                                )
                        )
                        ||
                        hits[0]
                };
            }


            node=parent;
        }


        return null;
    }


    function v5102CreateCard(
        count
    ){

        const result=
            v5102FindStatsGrid();


        if(!result){
            return false;
        }


        const grid=
            result.grid;

        const card24=
            result.card24;


        grid.style.gridTemplateColumns=
            "repeat(4,minmax(0,1fr))";


        let card=
            document.getElementById(
                "v5102Card1h"
            );


        if(!card){

            card=
                card24.cloneNode(
                    true
                );


            card.id=
                "v5102Card1h";


            const oldCount=
                card.querySelector(
                    "#v5Count24"
                );


            const oldRate=
                card.querySelector(
                    "#v5Rate24"
                );


            if(oldCount){

                oldCount.id=
                    "v5102Count1h";
            }


            if(oldRate){

                oldRate.id=
                    "v5102Rate1h";
            }


            /*
             * Nie zostawiamy innych powielonych ID.
             */
            card.querySelectorAll(
                "[id]"
            ).forEach(
                el => {

                    if(
                        el.id
                        !==
                        "v5102Count1h"
                        &&
                        el.id
                        !==
                        "v5102Rate1h"
                    ){

                        el.removeAttribute(
                            "id"
                        );
                    }
                }
            );


            const leaves=[
                ...card.querySelectorAll(
                    "*"
                )
            ];


            const label=
                leaves.find(
                    el =>
                        el.children.length===0
                        &&
                        (
                            el.textContent
                            ||
                            ""
                        )
                        .trim()
                        .toUpperCase()
                        ===
                        "OSTATNIE 24 H"
                );


            if(label){

                label.textContent=
                    "OSTATNIA 1 H";
            }


            grid.insertBefore(
                card,
                grid.firstElementChild
            );
        }


        const countNode=
            document.getElementById(
                "v5102Count1h"
            );


        const rateNode=
            document.getElementById(
                "v5102Rate1h"
            );


        if(countNode){

            countNode.textContent=
                String(
                    count
                );
        }


        if(rateNode){

            rateNode.textContent=
                "średnio "
                +
                Number(
                    count
                ).toFixed(
                    2
                )
                +
                " / h";
        }


        return true;
    }


    // ========================================================
    // WYKRES 30 DNI
    // ========================================================

    function v5102Ensure30dChart(){

        let box=
            document.getElementById(
                "v5102Box30d"
            );


        if(box){
            return box;
        }


        const chart7=
            document.getElementById(
                "v510Chart7d"
            );


        if(!chart7){
            return null;
        }


        const box7=
            chart7.closest(
                ".v510-chart-box"
            );


        if(!box7){
            return null;
        }


        box=
            document.createElement(
                "div"
            );


        box.id=
            "v5102Box30d";

        box.className=
            "v510-chart-box";


        box.innerHTML=`
            <div class="v510-chart-head">

                <div class="v510-chart-title">
                    OSTATNIE 30 DNI
                </div>

                <div
                    id="v5102Sum30d"
                    class="v510-chart-summary">
                </div>

            </div>

            <canvas
                id="v5102Chart30d"
                class="v510-chart-canvas">
            </canvas>
        `;


        box7.insertAdjacentElement(
            "afterend",
            box
        );


        return box;
    }


    function v5102Draw(
        canvas,
        data
    ){

        if(!canvas){
            return;
        }


        const rect=
            canvas.getBoundingClientRect();


        const width=
            Math.max(
                400,
                Math.round(
                    rect.width
                    ||
                    900
                )
            );


        const height=
            Math.max(
                140,
                Math.round(
                    rect.height
                    ||
                    165
                )
            );


        const dpr=
            Math.max(
                1,
                window.devicePixelRatio
                ||
                1
            );


        canvas.width=
            Math.round(
                width*dpr
            );

        canvas.height=
            Math.round(
                height*dpr
            );


        const ctx=
            canvas.getContext(
                "2d"
            );


        ctx.setTransform(
            dpr,
            0,
            0,
            dpr,
            0,
            0
        );


        ctx.clearRect(
            0,
            0,
            width,
            height
        );


        const left=34;
        const right=8;
        const top=14;
        const bottom=27;


        const chartWidth=
            width
            -
            left
            -
            right;


        const chartHeight=
            height
            -
            top
            -
            bottom;


        const maxValue=
            Math.max(
                1,
                ...data.bins
            );


        /*
         * Siatka.
         */
        ctx.strokeStyle=
            "#172731";

        ctx.lineWidth=1;


        for(
            let i=0;
            i<=4;
            i++
        ){

            const y=
                top
                +
                chartHeight
                -
                chartHeight*i/4;


            ctx.beginPath();

            ctx.moveTo(
                left,
                y
            );

            ctx.lineTo(
                left+chartWidth,
                y
            );

            ctx.stroke();
        }


        ctx.strokeStyle=
            "#283b48";


        ctx.beginPath();

        ctx.moveTo(
            left,
            top
        );

        ctx.lineTo(
            left,
            top+chartHeight
        );

        ctx.lineTo(
            left+chartWidth,
            top+chartHeight
        );

        ctx.stroke();


        const slot=
            chartWidth
            /
            30;


        const barWidth=
            Math.max(
                3,
                slot*0.76
            );


        for(
            let i=0;
            i<30;
            i++
        ){

            const value=
                data.bins[i];


            const h=
                value
                /
                maxValue
                *
                chartHeight;


            const x=
                left
                +
                i*slot
                +
                (
                    slot
                    -
                    barWidth
                )/2;


            const y=
                top
                +
                chartHeight
                -
                h;


            ctx.fillStyle=
                "#55b7d8";


            ctx.fillRect(
                x,
                y,
                barWidth,
                h
            );


            /*
             * Pokazujemy liczbę tylko
             * nad niezerowym słupkiem.
             */
            if(value > 0){

                ctx.fillStyle=
                    "#bed1dc";

                ctx.font=
                    "8px sans-serif";

                ctx.textAlign=
                    "center";


                ctx.fillText(
                    String(
                        value
                    ),
                    x+barWidth/2,
                    Math.max(
                        top+8,
                        y-3
                    )
                );
            }


            /*
             * Data co 5 dni + ostatni dzień.
             */
            if(
                i % 5 === 0
                ||
                i === 29
            ){

                ctx.fillStyle=
                    "#8095a4";

                ctx.font=
                    "9px sans-serif";

                ctx.textAlign=
                    "center";


                ctx.fillText(
                    data.labels[i],
                    left
                    +
                    i*slot
                    +
                    slot/2,
                    height-8
                );
            }
        }


        ctx.fillStyle=
            "#92a7b6";

        ctx.font=
            "9px sans-serif";

        ctx.textAlign=
            "left";


        ctx.fillText(
            "max "
            +
            maxValue,
            3,
            top+8
        );
    }


    // ========================================================
    // REFRESH
    // ========================================================

    async function v5102Refresh(){

        try{

            const items=
                await v5102FetchAll();


            const dates=
                items
                .map(
                    item =>
                        v5102ParseDate(
                            item.time
                        )
                )
                .filter(
                    Boolean
                );


            const now=
                new Date();


            const oneHour=
                v5102OneHour(
                    dates,
                    now
                );


            const thirty=
                v5102ThirtyDays(
                    dates,
                    now
                );


            v5102CreateCard(
                oneHour.count
            );


            const box=
                v5102Ensure30dChart();


            if(box){

                const summary=
                    document.getElementById(
                        "v5102Sum30d"
                    );


                if(summary){

                    summary.textContent=
                        thirty.total
                        +
                        " detekcji · 1 dzień / słupek";
                }


                requestAnimationFrame(
                    () => {

                        v5102Draw(
                            document.getElementById(
                                "v5102Chart30d"
                            ),
                            thirty
                        );
                    }
                );
            }


            return true;

        }catch(error){

            console.error(
                "V5.10.2 FIX:",
                error
            );


            return false;
        }
    }


    function v5102Start(){

        // V511:
        // bez pobierania całej historii
        // podczas zwykłego ładowania dashboardu.
        //
        // v5102Refresh() pozostaje wywoływany
        // przez kliknięcie STATYSTYKA.

    }


    /*
     * Aktualizacja po każdym otwarciu STATYSTYKI.
     */
    document.addEventListener(
        "click",
        event => {

            const button=
                event.target.closest
                ?
                event.target.closest(
                    "#v59StatsButton"
                )
                :
                null;


            if(button){

                setTimeout(
                    v5102Refresh,
                    80
                );

                setTimeout(
                    v5102Refresh,
                    300
                );
            }
        }
    );


    window.addEventListener(
        "resize",
        () => {

            const modal=
                document.getElementById(
                    "v59StatsModal"
                );


            if(
                modal
                &&
                modal.classList.contains(
                    "open"
                )
            ){

                setTimeout(
                    v5102Refresh,
                    80
                );
            }
        }
    );


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            v5102Start,
            {
                once:true
            }
        );

    }else{

        v5102Start();
    }

})();

</script>


<!-- V562_POINT_SCORE_UI_V2 -->

<style id="v562-point-score-style">

#detClassification.v562-score-box{
    visibility:visible;
    padding:12px;
    border-radius:10px;
    transition:
        border-color .18s ease,
        background .18s ease,
        box-shadow .18s ease;
}

.v562-score-head{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:14px;
}

.v562-score-caption{
    font-size:11px;
    letter-spacing:.10em;
    text-transform:uppercase;
    opacity:.66;
}

.v562-score-value{
    font-size:28px;
    font-weight:850;
    line-height:1;
}

.v562-feature-grid{
    display:grid;
    grid-template-columns:
        repeat(
            auto-fit,
            minmax(105px,1fr)
        );
    gap:6px;
    margin-top:11px;
}

.v562-feature{
    text-align:center;
    padding:6px 7px;
    border-radius:7px;
    font-size:11px;
    font-weight:750;
    border:
        1px solid
        rgba(255,255,255,.10);
    background:
        rgba(255,255,255,.035);
}

.v562-feature.ok{
    color:#b9ffc8;
    border-color:
        rgba(65,220,105,.45);
    background:
        rgba(65,220,105,.10);
}

.v562-feature.no{
    opacity:.45;
}

.v562-feature-symbol{
    display:inline-block;
    width:15px;
}

.v562-score-note{
    margin-top:9px;
    font-size:10px;
    opacity:.55;
}

</style>


<script id="v562-point-score-script">

(function(){

    "use strict";


    const CACHE_KEY =
        "meteorradio-v562-point-classifications";

    const OLD_CACHE_KEY =
        "meteorradio-v56-classifications";


    const FEATURE_ORDER = [

        ["head_echo","HEAD"],
        ["trail","TRAIL"],
        ["join","JOIN"],
        ["narrow","NARROW"],
        ["duration","DURATION"],
        ["peak","PEAK"],
        ["continuity","CONTINUITY"],
    ];


    function clampScore(value){

        let score=
            Number(
                value
            );

        if(
            !Number.isFinite(
                score
            )
        ){

            score=1;
        }

        return Math.max(
            1,
            Math.min(
                7,
                Math.round(
                    score
                )
            )
        );
    }


    function scoreHue(score){

        /*
         * 1 ->   0° czerwony
         * 2 ->  20°
         * 3 ->  40°
         * 4 ->  60° żółty
         * 5 ->  80°
         * 6 -> 100°
         * 7 -> 120° zielony
         */

        return (
            (
                clampScore(
                    score
                )
                -
                1
            )
            *
            20
        );
    }


    function esc(value){

        return String(
            value ?? ""
        )
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
    }


    function readCache(){

        try{

            return JSON.parse(
                localStorage.getItem(
                    CACHE_KEY
                )
                ||
                "{}"
            );

        }catch(_){

            return {};
        }
    }


    function saveCache(
        file,
        data
    ){

        try{

            const cache=
                readCache();

            cache[file]=data;

            localStorage.setItem(
                CACHE_KEY,
                JSON.stringify(
                    cache
                )
            );


            /*
             * Starsze sortowanie panelu
             * czyta stary klucz.
             *
             * Zapisujemy tam TEN SAM wynik,
             * ale confidence ma już wartość 1..7.
             */

            let legacy={};

            try{

                legacy=JSON.parse(
                    localStorage.getItem(
                        OLD_CACHE_KEY
                    )
                    ||
                    "{}"
                );

            }catch(_){

                legacy={};
            }


            legacy[file]=data;


            localStorage.setItem(
                OLD_CACHE_KEY,
                JSON.stringify(
                    legacy
                )
            );


        }catch(_){
        }
    }


    function ensureBox(){

        const detail=
            document.getElementById(
                "detDetail"
            );


        if(!detail){

            return null;
        }


        let box=
            document.getElementById(
                "detClassification"
            );


        if(!box){

            box=
                document.createElement(
                    "div"
                );

            box.id=
                "detClassification";

            detail.appendChild(
                box
            );
        }


        return box;
    }


    function renderScore(
        file,
        data
    ){

        const box=
            ensureBox();


        if(!box){

            return;
        }


        const score=
            clampScore(
                data.score
            );


        const hue=
            scoreHue(
                score
            );


        box.className=
            "v562-score-box";

        box.dataset.v562File=
            file;


        box.style.borderColor=
            `hsl(${hue} 90% 48%)`;


        box.style.background=
            (
                `linear-gradient(
                    135deg,
                    hsl(${hue} 80% 45% / .18),
                    rgba(5,8,12,.90)
                )`
            );


        box.style.boxShadow=
            (
                `0 0 22px
                 hsl(${hue} 85% 48% / .10)`
            );


        const features=
            data.features
            ||
            {};


        const featureHtml=
            FEATURE_ORDER
            .map(
                ([key,label])=>{

                    const item=
                        features[key];

                    const passed=
                        (
                            item
                            &&
                            typeof item
                                ===
                                "object"
                        )
                        ?
                        !!item.passed
                        :
                        !!item;


                    return (
                        '<div class="v562-feature '
                        +
                        (
                            passed
                            ?
                            'ok'
                            :
                            'no'
                        )
                        +
                        '">'
                        +
                        '<span class="v562-feature-symbol">'
                        +
                        (
                            passed
                            ?
                            '✓'
                            :
                            '×'
                        )
                        +
                        '</span>'
                        +
                        esc(
                            label
                        )
                        +
                        '</div>'
                    );
                }
            )
            .join("");


        box.innerHTML=
            '<div class="v562-score-head">'
            +
                '<div class="v562-score-caption">'
                +
                    'OCENA DETEKCJI'
                +
                '</div>'
            +
                '<div class="v562-score-value" '
                +
                    'style="color:'
                    +
                    `hsl(${hue} 92% 62%)`
                    +
                    '">'
                +
                    String(score)
                +
                '</div>'
            +
            '</div>'
            +
            '<div class="v562-feature-grid">'
            +
                featureHtml
            +
            '</div>'
            +
            '<div class="v562-score-note">'
            +
                'Skala punktowa 1–7 · '
                +
                'HEAD · TRAIL · JOIN · NARROW · '
                +
                'DURATION · PEAK · CONTINUITY'
            +
            '</div>';
    }


    async function loadPointClassification(
        item,
        seq
    ){

        if(
            !item
            ||
            !item.file
        ){

            return;
        }


        const file=
            item.file;


        const cache=
            readCache();


        const cached=
            cache[
                file
            ];


        if(
            cached
            &&
            cached.heuristic_version
                ===
                "v5.6.2-anchor-head-trail-points-v1"
        ){

            renderScore(
                file,
                cached
            );

            return;
        }


        const box=
            ensureBox();


        if(box){

            box.className=
                "v562-score-box";

            box.innerHTML=
                '<div class="v562-score-caption">'
                +
                    'OCENA DETEKCJI — LICZĘ…'
                +
                '</div>';
        }


        try{

            const response=
                await fetch(
                    "/api/classification?file="
                    +
                    encodeURIComponent(
                        file
                    )
                    +
                    "&v=562p1",
                    {
                        cache:
                            "no-store"
                    }
                );


            const data=
                await response.json();


            if(
                !data
                ||
                !data.ok
            ){

                throw new Error(
                    (
                        data
                        &&
                        data.error
                    )
                    ||
                    "classification failed"
                );
            }


            if(
                typeof selectedDetectionFile
                    !==
                    "undefined"
                &&
                selectedDetectionFile
                    !==
                    file
            ){

                return;
            }


            saveCache(
                file,
                data
            );


            renderScore(
                file,
                data
            );


        }catch(error){

            const current=
                ensureBox();


            if(current){

                current.className=
                    "v562-score-box";

                current.innerHTML=
                    '<div class="v562-score-caption">'
                    +
                        'OCENA — BŁĄD'
                    +
                    '</div>'
                    +
                    '<div class="v562-score-note">'
                    +
                        esc(
                            String(
                                error
                            )
                        )
                    +
                    '</div>';
            }
        }
    }


    /*
     * Stary procentowy cache usuwamy.
     * Ulubionych nie dotykamy.
     */

    try{

        localStorage.removeItem(
            OLD_CACHE_KEY
        );

    }catch(_){
    }


    /*
     * Podmiana starego loadera.
     */

    try{

        v5LoadClassification=
            loadPointClassification;

    }catch(_){

        window.v5LoadClassification=
            loadPointClassification;
    }


    window.v562LoadClassification=
        loadPointClassification;


    /*
     * Zamiana napisu PEWNOŚĆ -> OCENA
     * w istniejących kontrolkach sortowania.
     */

    function renameConfidenceLabels(){

        document
        .querySelectorAll(
            "button,option,label,span"
        )
        .forEach(
            el=>{

                if(
                    el.children.length
                    !==
                    0
                ){

                    return;
                }


                const text=
                    el.textContent;


                if(!text){

                    return;
                }


                if(
                    /pewność/i.test(
                        text
                    )
                ){

                    el.textContent=
                        text.replace(
                            /pewność/gi,
                            "OCENA ↓"
                        );
                }
            }
        );
    }


    renameConfidenceLabels();


    /* V562_AUTOLOAD_DISABLED */

    console.log(
        "MeteorRadio V5.6.2 point score UI active"
    );

})();

</script>



<!-- V562_UI_LIGHT_PRERENDER -->

<style id="v562-light-ui-style">

.v562-list-score{
    font-weight:850;
    margin-right:7px;
    white-space:nowrap;
}

</style>


<script id="v562-light-ui-script">

(function(){

    "use strict";


    const POINT_KEY =
        "meteorradio-v562-point-classifications";

    const LEGACY_KEY =
        "meteorradio-v56-classifications";


    let serverScoreIndex={};


    function readStorage(key){

        try{

            return JSON.parse(
                localStorage.getItem(
                    key
                )
                ||
                "{}"
            );

        }catch(_){

            return {};
        }
    }


    function scoreForFile(file){

        if(!file){
            return null;
        }


        const point=
            readStorage(
                POINT_KEY
            )[file];


        if(point){

            const s=Number(
                point.score
            );

            if(
                Number.isFinite(s)
                &&
                s >= 1
                &&
                s <= 7
            ){

                return Math.round(s);
            }
        }


        const server=
            Number(
                serverScoreIndex[
                    file
                ]
            );


        if(
            Number.isFinite(server)
            &&
            server >= 1
            &&
            server <= 7
        ){

            return Math.round(
                server
            );
        }


        const legacy=
            readStorage(
                LEGACY_KEY
            )[file];


        if(
            legacy
            &&
            legacy.confidence_semantics
                ===
                "points_1_to_7_not_percent"
        ){

            const s=Number(
                legacy.score
                ??
                legacy.confidence
            );

            if(
                Number.isFinite(s)
                &&
                s >= 1
                &&
                s <= 7
            ){

                return Math.round(s);
            }
        }


        return null;
    }


    function hueForScore(score){

        return (
            Math.max(
                1,
                Math.min(
                    7,
                    score
                )
            )
            -
            1
        )
        *
        20;
    }


    function removePercentageText(root){

        if(!root){
            return;
        }


        const walker=
            document.createTreeWalker(
                root,
                NodeFilter.SHOW_TEXT
            );


        const nodes=[];


        while(
            walker.nextNode()
        ){

            nodes.push(
                walker.currentNode
            );
        }


        nodes.forEach(
            node=>{

                const old=
                    node.nodeValue
                    ||
                    "";


                if(
                    /\b\d{1,3}%\b/.test(
                        old
                    )
                ){

                    node.nodeValue=
                        old.replace(
                            /\b\d{1,3}%\b/g,
                            ""
                        );
                }
            }
        );
    }


    function fixDetectionRows(){

        const list=
            document.getElementById(
                "detList"
            );


        if(!list){
            return;
        }


        list
        .querySelectorAll(
            ".det-row"
        )
        .forEach(
            row=>{

                const file=
                    row.dataset.file;

                const score=
                    scoreForFile(
                        file
                    );


                removePercentageText(
                    row
                );


                row
                .querySelectorAll(
                    ".v562-list-score"
                )
                .forEach(
                    el=>el.remove()
                );


                if(score === null){
                    return;
                }


                const target=
                    row.querySelector(
                        ".det-row-snr"
                    );


                if(!target){
                    return;
                }


                const badge=
                    document.createElement(
                        "span"
                    );


                badge.className=
                    "v562-list-score";


                
        badge.textContent =
            String(score);
        


                const hue=
                    hueForScore(
                        score
                    );


                badge.style.color=
                    `hsl(${hue} 92% 62%)`;


                target.appendChild(
                    badge
                );
            }
        );
    }


    function removeOldScoreControls(){

        document
        .querySelectorAll(
            "select"
        )
        .forEach(
            select=>{

                const options=[
                    ...select.options
                ];


                const percent=
                    options.filter(
                        option=>
                            /(?:ocena|pewność)/i.test(
                                option.textContent
                                ||
                                ""
                            )
                            &&
                            /%/.test(
                                option.textContent
                                ||
                                ""
                            )
                    );


                if(percent.length){

                    const selectedWasOld=
                        percent.includes(
                            select.selectedOptions[
                                0
                            ]
                        );


                    percent.forEach(
                        option=>
                            option.remove()
                    );


                    if(selectedWasOld){

                        const all=[
                            ...select.options
                        ].find(
                            option=>
                                /wszystkie/i.test(
                                    option.textContent
                                    ||
                                    ""
                                )
                        );


                        if(all){

                            select.value=
                                all.value;

                            select.dispatchEvent(
                                new Event(
                                    "change",
                                    {
                                        bubbles:true
                                    }
                                )
                            );
                        }
                    }
                }


                /*
                 * Na razie usuwamy również stare
                 * sortowanie OCENA/PEWNOŚĆ.
                 *
                 * Ono należało do dawnego systemu
                 * procentowego i potrafiło wymuszać
                 * masową analizę.
                 */

                const scoreSort=[
                    ...select.options
                ].filter(
                    option=>
                        /^(?:ocena|pewność)\s*[↑↓]/i.test(
                            (
                                option.textContent
                                ||
                                ""
                            ).trim()
                        )
                );


                if(scoreSort.length){

                    const selectedWasScore=
                        scoreSort.includes(
                            select.selectedOptions[
                                0
                            ]
                        );


                    scoreSort.forEach(
                        option=>
                            option.remove()
                    );


                    if(selectedWasScore){

                        const newest=[
                            ...select.options
                        ].find(
                            option=>
                                /najnowsze/i.test(
                                    option.textContent
                                    ||
                                    ""
                                )
                        );


                        if(newest){

                            select.value=
                                newest.value;

                            select.dispatchEvent(
                                new Event(
                                    "change",
                                    {
                                        bubbles:true
                                    }
                                )
                            );
                        }
                    }
                }
            }
        );


        /*
         * "Filtr" zostaje tylko jako:
         * Wszystkie / Ulubione.
         */

        document
        .querySelectorAll(
            "span,label,div"
        )
        .forEach(
            el=>{

                if(
                    el.children.length
                    !==
                    0
                ){
                    return;
                }


                if(
                    (
                        el.textContent
                        ||
                        ""
                    ).trim()
                    ===
                    "Filtr:"
                ){

                    el.textContent=
                        "Widok:";
                }
            }
        );


        /*
         * Przycisk masowego przeliczania
         * nie jest już potrzebny.
         */

        document
        .querySelectorAll(
            "button"
        )
        .forEach(
            button=>{

                const text=(
                    button.textContent
                    ||
                    ""
                ).trim();


                if(
                    /przelicz/i.test(text)
                    ||
                    /oceny:\s*na\s*żądanie/i.test(text)
                ){

                    button.style.display=
                        "none";
                }
            }
        );
    }


    function readableThrottle(){

        const leaves=[
            ...document.querySelectorAll(
                "div,span,small"
            )
        ];


        const detail=
            leaves.find(
                el=>
                    el.children.length
                        ===
                        0
                    &&
                    /^get_throttled=0x/i.test(
                        (
                            el.textContent
                            ||
                            ""
                        ).trim()
                    )
            );


        if(!detail){
            return;
        }


        const match=(
            detail.textContent
            ||
            ""
        ).match(
            /0x([0-9a-f]+)/i
        );


        if(!match){
            return;
        }


        const raw=
            parseInt(
                match[1],
                16
            );


        const current=
            raw
            &
            0xF;


        const history=
            (
                raw
                >>>
                16
            )
            &
            0xF;


        const names=[
            "niskie napięcie",
            "limit taktowania",
            "throttling",
            "limit temperatury"
        ];


        function decode(bits){

            const out=[];

            for(
                let i=0;
                i<4;
                i++
            ){

                if(
                    bits
                    &
                    (
                        1 << i
                    )
                ){

                    out.push(
                        names[i]
                    );
                }
            }

            return out;
        }


        let box=
            detail.parentElement;


        for(
            let i=0;
            i<3
            &&
            box
            &&
            box.parentElement;
            i++
        ){

            if(
                /card|health|metric/i.test(
                    String(
                        box.className
                    )
                )
            ){
                break;
            }

            box=
                box.parentElement;
        }


        const candidates=
            box
            ?
            [
                ...box.querySelectorAll(
                    "div,span"
                )
            ]
            :
            [];


        const value=
            candidates.find(
                el=>
                    el.children.length
                        ===
                        0
                    &&
                    (
                        /^0x[0-9a-f]+$/i.test(
                            (
                                el.textContent
                                ||
                                ""
                            ).trim()
                        )
                        ||
                        /^(?:OK|UWAGA)$/i.test(
                            (
                                el.textContent
                                ||
                                ""
                            ).trim()
                        )
                    )
            );


        if(current === 0){

            if(value){

                value.textContent=
                    "OK";

                value.style.color=
                    "#7ef29a";
            }


            const old=
                decode(
                    history
                );


            detail.textContent=
                old.length
                ?
                (
                    "teraz OK · historia: "
                    +
                    old.join(", ")
                )
                :
                "brak throttlingu";

        }else{

            if(value){

                value.textContent=
                    "UWAGA";

                value.style.color=
                    "#ffb454";
            }


            detail.textContent=
                (
                    "aktywne: "
                    +
                    decode(
                        current
                    ).join(", ")
                );
        }
    }


    async function loadServerScores(){

        try{

            const response=
                await fetch(
                    "/api/score-index?t="
                    +
                    Date.now(),
                    {
                        cache:
                            "no-store"
                    }
                );


            const d=
                await response.json();


            serverScoreIndex=
                d.scores
                ||
                {};


            /*
             * Stare sortowanie czytało LEGACY_KEY.
             * Wstawiamy tam lekkie wyniki punktowe,
             * ale NIE do POINT_KEY, żeby otwarcie
             * detekcji nadal mogło pobrać komplet
             * siedmiu cech.
             */

            const legacy=
                readStorage(
                    LEGACY_KEY
                );


            Object.entries(
                serverScoreIndex
            )
            .forEach(
                ([file,score])=>{

                    legacy[file]={
                        score:
                            score,

                        confidence:
                            score,

                        confidence_semantics:
                            "points_1_to_7_not_percent",

                        index_only:
                            true,
                    };
                }
            );


            localStorage.setItem(
                LEGACY_KEY,
                JSON.stringify(
                    legacy
                )
            );


            fixDetectionRows();


        }catch(error){

            console.warn(
                "score-index",
                error
            );
        }
    }


    removeOldScoreControls();

    readableThrottle();

    loadServerScores();


    /*
     * V562_FIREFOX_LOOP_FIX
     *
     * Nie używamy MutationObserver.
     *
     * Lista detekcji jest odświeżana przez dashboard,
     * a nasze punkty x/7 uzupełnia lekki timer.
     *
     * Dzięki temu zmiana badge nie wywołuje samej siebie.
     */

    /* MR_SCORE_NO_FLICKER_HOOK_V1 */
    window.__mrScoreAfterRender =
        function(){
            fixDetectionRows();
        };

    fixDetectionRows();
    readableThrottle();


    /*
     * Bardzo lekki housekeeping.
     * Nie wykonuje klasyfikacji ani FFT.
     */

    setInterval(
        ()=>{
            fixDetectionRows();
            readableThrottle();
        },
        10000
    );


    console.log(
        "MeteorRadio lightweight UI active"
    );

})();

</script>


<!-- V562_FINAL_UI_CLEANUP -->

<style id="v562-final-cleanup-style">

/*
 * Stary procentowy confidence V5.4.
 *
 * Nowa skala to wyłącznie 1/7 ... 7/7.
 */

.v54-conf-green,
.v54-conf-yellow,
.v54-conf-orange,
.v54-conf-red{
    display:none !important;
}


/*
 * Stary filtr/widok.
 *
 * Logika pozostaje w kodzie dla kompatybilności,
 * ale użytkownik go nie potrzebuje.
 */

#v53DetectionFilter{
    display:none !important;
}

</style>


<script id="v562-final-cleanup-script">

(function(){

    "use strict";


    function cleanupOldPercentages(){

        document
        .querySelectorAll(
            ".det-row"
        )
        .forEach(
            row=>{

                /*
                 * Najpierw znane stare badge V5.4.
                 */

                row
                .querySelectorAll(
                    ".v54-conf-green,"
                    +
                    ".v54-conf-yellow,"
                    +
                    ".v54-conf-orange,"
                    +
                    ".v54-conf-red"
                )
                .forEach(
                    el=>el.remove()
                );


                /*
                 * Fallback na wypadek, gdy któryś
                 * dawny renderer procentu nie ma klasy.
                 */

                const walker=
                    document.createTreeWalker(
                        row,
                        NodeFilter.SHOW_TEXT
                    );


                const nodes=[];


                while(
                    walker.nextNode()
                ){

                    nodes.push(
                        walker.currentNode
                    );
                }


                nodes.forEach(
                    node=>{

                        const text=
                            node.nodeValue
                            ||
                            "";


                        if(
                            /\d{1,3}\s*%/.test(
                                text
                            )
                        ){

                            node.nodeValue=
                                text.replace(
                                    /\d{1,3}\s*%/g,
                                    ""
                                );
                        }
                    }
                );
            }
        );
    }


    function removeViewControl(){

        const filter=
            document.getElementById(
                "v53DetectionFilter"
            );


        if(!filter){

            return;
        }


        /*
         * Zostawiamy wewnętrznie tryb Wszystkie,
         * ale chowamy kontrolkę.
         */

        const all=[
            ...filter.options
        ].find(
            option=>
                /wszystkie/i.test(
                    option.textContent
                    ||
                    ""
                )
        );


        if(all){

            filter.value=
                all.value;
        }


        filter.style.display=
            "none";


        /*
         * Usuwamy napis Widok: / Filtr:
         * stojący obok selecta.
         */

        const parent=
            filter.parentNode;


        if(parent){

            [
                ...parent.childNodes
            ]
            .forEach(
                node=>{

                    if(
                        node
                        ===
                        filter
                    ){
                        return;
                    }


                    const text=(
                        node.textContent
                        ||
                        ""
                    ).trim();


                    if(
                        /^(widok|filtr)\s*:?\s*$/i.test(
                            text
                        )
                    ){

                        if(
                            node.nodeType
                            ===
                            Node.TEXT_NODE
                        ){

                            node.nodeValue=
                                "";

                        }else if(
                            node.style
                        ){

                            node.style.display=
                                "none";
                        }
                    }
                }
            );
        }
    }


    /*
     * renderDetectionList jest wywoływany przy każdym
     * odświeżeniu listy.
     *
     * Podpinamy lekki cleanup BEZ MutationObservera,
     * więc nie wracamy do pętli Firefoksa.
     */

    try{

        if(
            typeof renderDetectionList
            ===
            "function"
            &&
            !renderDetectionList
                .v562CleanWrapped
        ){

            const original=
                renderDetectionList;


            const wrapped=
                function(list){

                    const result=
                        original(
                            list
                        );


                    cleanupOldPercentages();


                    return result;
                };


            wrapped.v562CleanWrapped=
                true;


            renderDetectionList=
                wrapped;


            console.log(
                "renderDetectionList cleanup wrapper active"
            );
        }

    }catch(error){

        console.warn(
            "render wrapper",
            error
        );
    }


    removeViewControl();

    cleanupOldPercentages();


    /*
     * Dwa jednorazowe powtórzenia po starcie.
     * Żadnego ciągłego obserwatora DOM.
     */

    setTimeout(
        ()=>{
            removeViewControl();
            cleanupOldPercentages();
        },
        500
    );


    setTimeout(
        ()=>{
            removeViewControl();
            cleanupOldPercentages();
        },
        2000
    );


    console.log(
        "V562_FINAL_UI_CLEANUP active"
    );

})();

</script>


<!-- MR_SCORE_STABLE_PATCH_V1 -->
<style>
.mr-score-badge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:34px;
  height:18px;
  padding:0 6px;
  margin-right:8px;
  border-radius:6px;
  font-size:12px;
  font-weight:800;
  line-height:1;
  letter-spacing:.2px;
  border:1px solid rgba(255,255,255,.12);
  background:rgba(255,255,255,.04);
  color:#cfe8ff;
  vertical-align:middle;
  white-space:nowrap;
}
.mr-score-badge.s1{ color:#ff6b6b; border-color:rgba(255,107,107,.45); background:rgba(255,107,107,.10); }
.mr-score-badge.s2{ color:#ff8b6b; border-color:rgba(255,139,107,.45); background:rgba(255,139,107,.10); }
.mr-score-badge.s3{ color:#ffad66; border-color:rgba(255,173,102,.45); background:rgba(255,173,102,.10); }
.mr-score-badge.s4{ color:#ffd166; border-color:rgba(255,209,102,.45); background:rgba(255,209,102,.10); }
.mr-score-badge.s5{ color:#c7f36b; border-color:rgba(199,243,107,.45); background:rgba(199,243,107,.10); }
.mr-score-badge.s6{ color:#7ee787; border-color:rgba(126,231,135,.45); background:rgba(126,231,135,.10); }
.mr-score-badge.s7{ color:#39d353; border-color:rgba(57,211,83,.45); background:rgba(57,211,83,.12); }
</style>

<script>
(function(){
  if (window.__mrScoreStablePatchLoaded) return;
  window.__mrScoreStablePatchLoaded = true;

  const SCORE_CACHE = new Map();

  function getRowFileKey(row){
    if (!row) return null;
    const df = row.getAttribute && row.getAttribute('data-file');
    if (df) return df;
    const txt = row.textContent || '';
    const m = txt.match(/SMP_[A-Za-z0-9_.-]+\.npz/);
    return m ? m[0] : null;
  }

  function getScoreFromText(txt){
    const m = (txt || '').match(/\b([1-7])\/7\b/);
    return m ? m[0] : null;
  }

  function scoreClass(scoreText){
    const n = parseInt((scoreText || '0').split('/')[0], 10);
    if (!n || n < 1 || n > 7) return '';
    return 's' + n;
  }

  function maybeRowElements(){
    const sels = [
      '[data-file]',
      '.detection-row',
      '.detection-item',
      '.detection-entry',
      '.list-row',
      '.list-item'
    ];
    const out = [];
    sels.forEach(sel => document.querySelectorAll(sel).forEach(el => out.push(el)));
    return Array.from(new Set(out));
  }

  function ensureScoreBadge(row, scoreText){
    if (!row || !scoreText) return;

    let badge = row.querySelector('.mr-score-badge');
    if (!badge){
      badge = document.createElement('span');
      badge.className = 'mr-score-badge';

      // próbujemy wstawić badge wysoko w wierszu, przed SNR
      let target = null;
      const candidates = row.querySelectorAll('span, div, strong, b');
      for (const el of candidates){
        const t = (el.textContent || '').trim();
        if (/^\d+(\.\d+)?\s*dB$/.test(t) || /dB/.test(t)) {
          target = el;
          break;
        }
      }

      if (target && target.parentNode){
        target.parentNode.insertBefore(badge, target);
      } else if (row.firstChild){
        row.insertBefore(badge, row.firstChild);
      } else {
        row.appendChild(badge);
      }
    }

    badge.textContent = scoreText;
    badge.className = 'mr-score-badge ' + scoreClass(scoreText);
  }

  function cacheVisibleScores(){
    const rows = maybeRowElements();
    rows.forEach(row => {
      const key = getRowFileKey(row);
      if (!key) return;
      const txt = row.textContent || '';
      const score = getScoreFromText(txt);
      if (score) {
        SCORE_CACHE.set(key, score);
        ensureScoreBadge(row, score);
      }
    });
  }

  function restoreMissingScores(){
    const rows = maybeRowElements();
    rows.forEach(row => {
      const key = getRowFileKey(row);
      if (!key) return;

      const txt = row.textContent || '';
      const hasVisible = getScoreFromText(txt);
      if (hasVisible) {
        ensureScoreBadge(row, hasVisible);
        return;
      }

      const cached = SCORE_CACHE.get(key);
      if (cached) {
        ensureScoreBadge(row, cached);
      }
    });
  }

  function patchSortDropdown(){
    const sels = Array.from(document.querySelectorAll('select'));
    const sortSel = sels.find(s => {
      const txt = (s.parentElement?.textContent || '') + ' ' + (s.name || '') + ' ' + (s.id || '');
      return /sort/i.test(txt);
    });
    if (!sortSel) return;

    let scoreOpt = Array.from(sortSel.options).find(o => o.value === 'score_desc' || o.value === 'score');
    if (!scoreOpt){
      scoreOpt = document.createElement('option');
      scoreOpt.value = 'score_desc';
      scoreOpt.textContent = 'OCENA ↓';
      sortSel.appendChild(scoreOpt);
    } else {
      scoreOpt.textContent = 'OCENA ↓';
      if (scoreOpt.value === 'score') scoreOpt.value = 'score_desc';
    }

    const snrOpt = Array.from(sortSel.options).find(o => o.value === 'snr_desc' || /SNR/.test(o.textContent || ''));
    if (snrOpt && !/↓/.test(snrOpt.textContent)) {
      snrOpt.textContent = 'SNR ↓';
    }
  }

  function runAll(){
    patchSortDropdown();
    cacheVisibleScores();
    restoreMissingScores();
  }

  document.addEventListener('DOMContentLoaded', () => {
    runAll();
    setTimeout(runAll, 300);
    setTimeout(runAll, 1200);
  });

  window.addEventListener('load', () => {
    runAll();
    setTimeout(runAll, 300);
    setTimeout(runAll, 1200);
  });

  
    /* MR_SCORE_STABLE interval disabled */
    
})();
</script>


<!-- MR_SCORE_DESC_HIGH_TO_LOW_V1 -->

<script>

(function(){

    "use strict";


    const POINT_KEY =
        "meteorradio-v562-point-classifications";

    const LEGACY_KEY =
        "meteorradio-v56-classifications";


    function readJson(key){

        try{

            return JSON.parse(
                localStorage.getItem(
                    key
                )
                ||
                "{}"
            );

        }catch(_){

            return {};
        }
    }


    function scoreOf(item){

        if(
            !item
            ||
            !item.file
        ){

            return -1;
        }


        const file=
            item.file;


        const point=
            readJson(
                POINT_KEY
            )[file];


        if(point){

            const n=Number(
                point.score
                ??
                point.confidence
            );


            if(
                Number.isFinite(n)
                &&
                n >= 1
                &&
                n <= 7
            ){

                return n;
            }
        }


        const legacy=
            readJson(
                LEGACY_KEY
            )[file];


        if(legacy){

            const n=Number(
                legacy.score
                ??
                legacy.confidence
            );


            if(
                Number.isFinite(n)
                &&
                n >= 1
                &&
                n <= 7
            ){

                return n;
            }
        }


        return -1;
    }


    function numericSNR(item){

        const n=Number(
            item
            &&
            item.snr_db
        );


        return Number.isFinite(n)
            ?
            n
            :
            -9999;
    }


    function timestampValue(item){

        const candidates=[
            item && item.timestamp,
            item && item.time,
            item && item.datetime,
            item && item.created_at,
        ];


        for(
            const value
            of candidates
        ){

            if(!value){
                continue;
            }


            const t=Date.parse(
                value
            );


            if(
                Number.isFinite(t)
            ){

                return t;
            }
        }


        return 0;
    }


    /*
     * Zapamiętujemy dotychczasową funkcję.
     * Wszystkie inne sposoby sortowania
     * nadal obsługuje stary silnik.
     */

    const originalSort=
        (
            typeof window.v55SortData
            ===
            "function"
        )
        ?
        window.v55SortData
        :
        (
            typeof v55SortData
            ===
            "function"
            ?
            v55SortData
            :
            null
        );


    function fixedSortData(data){

        const list=
            Array.isArray(data)
            ?
            [...data]
            :
            [];


        let mode="";


        try{

            const select=
                document.getElementById(
                    "v55DetectionSort"
                )
                ||
                [
                    ...document.querySelectorAll(
                        "select"
                    )
                ]
                .find(
                    s=>
                        [
                            ...s.options
                        ]
                        .some(
                            o=>
                                o.value
                                ===
                                "score_desc"
                        )
                );


            if(select){

                mode=
                    select.value
                    ||
                    "";
            }

        }catch(_){
        }


        if(
            mode
            !==
            "score_desc"
        ){

            if(originalSort){

                return originalSort(
                    data
                );
            }


            return list;
        }


        /*
         * KLUCZOWA POPRAWKA:
         *
         * B - A
         *
         * czyli:
         *
         * 7/7
         * 6/7
         * 5/7
         * ...
         * 1/7
         *
         * Brak oceny idzie na sam dół.
         */

        list.sort(
            (a,b)=>{

                const sa=
                    scoreOf(a);

                const sb=
                    scoreOf(b);


                if(
                    sa
                    !==
                    sb
                ){

                    return (
                        sb
                        -
                        sa
                    );
                }


                /*
                 * Przy takim samym wyniku:
                 * wyższy SNR pierwszy.
                 */

                const snrDiff=
                    numericSNR(b)
                    -
                    numericSNR(a);


                if(
                    Math.abs(
                        snrDiff
                    )
                    >
                    0.000001
                ){

                    return snrDiff;
                }


                /*
                 * Potem nowszy rekord.
                 */

                return (
                    timestampValue(b)
                    -
                    timestampValue(a)
                );
            }
        );


        return list;
    }


    /*
     * Nadpisujemy globalną funkcję V5.5.
     */

    try{

        window.v55SortData=
            fixedSortData;

    }catch(_){
    }


    try{

        v55SortData=
            fixedSortData;

    }catch(_){
    }


    /*
     * Upewniamy się, że etykieta oznacza
     * malejące sortowanie.
     */

    [
        ...document.querySelectorAll(
            "option"
        )
    ]
    .forEach(
        option=>{

            if(
                option.value
                ===
                "score_desc"
            ){

                option.textContent=
                    "OCENA ↓";
            }
        }
    );


    /*
     * Jeżeli OCENA ↓ jest już wybrana,
     * od razu odrysuj listę.
     */

    setTimeout(
        ()=>{

            try{

                const select=
                    [
                        ...document.querySelectorAll(
                            "select"
                        )
                    ]
                    .find(
                        s=>
                            s.value
                            ===
                            "score_desc"
                    );


                if(
                    select
                    &&
                    typeof renderDetectionList
                    ===
                    "function"
                    &&
                    typeof detectionsCache
                    !==
                    "undefined"
                ){

                    renderDetectionList(
                        detectionsCache
                    );
                }

            }catch(error){

                console.warn(
                    "score-desc refresh",
                    error
                );
            }

        },
        500
    );


    console.log(
        "OCENA DESC = HIGH TO LOW"
    );

})();

</script>


<!-- V562_SINGLE_SCORE_RIGHT_OF_DB_V1 -->

<style id="v562-single-score-right-style">

/*
 * Stary dodatkowy badge:
 * całkowicie niewidoczny.
 */

.mr-score-badge{
    display:none !important;
}


/*
 * JEDYNA widoczna ocena na liście.
 *
 * Jest częścią .det-row-snr i znajduje się
 * ZA tekstem dB.
 */

.v562-list-score{

    display:inline-flex !important;

    align-items:center;
    justify-content:center;

    box-sizing:border-box;

    min-width:29px;
    height:17px;

    padding:0 5px;

    margin-left:7px !important;
    margin-right:0 !important;

    border:
        1px solid
        rgba(65,220,105,.75);

    border-radius:5px;

    background:
        rgba(40,145,65,.18);

    font-size:10px;
    font-weight:850;

    line-height:15px;

    vertical-align:middle;

    white-space:nowrap;
}

</style>


<script id="v562-single-score-right-script">

(function(){

    "use strict";


    function cleanup(){

        /*
         * Kasujemy z DOM stare dodatkowe badge.
         * CSS i tak je ukrywa, ale nie chcemy
         * niepotrzebnych elementów.
         */

        document
        .querySelectorAll(
            ".mr-score-badge"
        )
        .forEach(
            el=>el.remove()
        );


        /*
         * Właściwy score to .v562-list-score.
         *
         * Jeżeli jakiś wcześniejszy kod go
         * znowu wstawi przed dB, przesuwamy go
         * na KONIEC .det-row-snr.
         */

        document
        .querySelectorAll(
            ".det-row-snr"
        )
        .forEach(
            target=>{

                const score=
                    target.querySelector(
                        ".v562-list-score"
                    );


                if(!score){
                    return;
                }


                if(
                    target.lastElementChild
                    !==
                    score
                ){

                    target.appendChild(
                        score
                    );
                }
            }
        );
    }


    /*
     * Jednorazowo po załadowaniu.
     * Bez MutationObserver.
     * Bez szybkiego interwału.
     */

    cleanup();


    setTimeout(
        cleanup,
        300
    );


    setTimeout(
        cleanup,
        1500
    );


    console.log(
        "single score right of dB active"
    );

})();

</script>


<!-- MR_REFRESH_5MIN_BUTTON_V2 -->

<style>

#mrRefreshNow{

    height:27px;
    padding:0 10px;

    margin-left:8px;

    border:
        1px solid
        rgba(105,145,170,.50);

    border-radius:5px;

    background:#172630;

    color:#d8e8f0;

    font-size:10px;
    font-weight:750;

    cursor:pointer;

    white-space:nowrap;
}


#mrRefreshNow:hover{
    background:#213945;
}


#mrRefreshNow:disabled{
    opacity:.55;
    cursor:default;
}


#mrRefreshAge{

    margin-left:7px;

    color:#768b98;

    font-size:9px;

    white-space:nowrap;
}

</style>


<script>

(function(){

    "use strict";


    const FIVE_MINUTES=
        300000;


    const SCORE_KEY=
        "meteorradio-v56-classifications";


    async function syncScores(){

        try{

            const r=
                await fetch(
                    "/api/score-index?t="
                    +
                    Date.now(),
                    {
                        cache:
                            "no-store"
                    }
                );


            if(!r.ok){
                return;
            }


            const d=
                await r.json();


            let store={};


            try{

                store=
                    JSON.parse(
                        localStorage.getItem(
                            SCORE_KEY
                        )
                        ||
                        "{}"
                    );

            }catch(_){

                store={};
            }


            Object.entries(
                d.scores
                ||
                {}
            )
            .forEach(
                ([file,value])=>{

                    const score=
                        Number(
                            value
                        );


                    if(
                        Number.isFinite(score)
                        &&
                        score >= 1
                        &&
                        score <= 7
                    ){

                        store[file]={
                            score:
                                score,

                            confidence:
                                score,

                            confidence_semantics:
                                "points_1_to_7_not_percent",

                            index_only:
                                true
                        };
                    }
                }
            );


            localStorage.setItem(
                SCORE_KEY,
                JSON.stringify(
                    store
                )
            );


        }catch(error){

            console.warn(
                "score sync",
                error
            );
        }
    }


    async function doRefresh(force){

        const button=
            document.getElementById(
                "mrRefreshNow"
            );


        if(button){

            button.disabled=true;

            button.textContent=
                "↻ Odświeżam…";
        }


        try{

            /*
             * Najpierw pobieramy już gotowe oceny.
             */

            await syncScores();


            /*
             * Dopiero potem odrysowujemy listę.
             */

            if(
                typeof refreshDetections
                ===
                "function"
            ){

                await refreshDetections(
                    Boolean(force)
                );
            }


            const age=
                document.getElementById(
                    "mrRefreshAge"
                );


            if(age){

                const now=
                    new Date();


                age.textContent=
                    (
                        "auto 5 min · "
                        +
                        now.toLocaleTimeString(
                            [],
                            {
                                hour:"2-digit",
                                minute:"2-digit"
                            }
                        )
                    );
            }


        }finally{

            if(button){

                button.disabled=false;

                button.textContent=
                    "↻ Odśwież teraz";
            }
        }
    }


    function installButton(){

        if(
            document.getElementById(
                "mrRefreshNow"
            )
        ){
            return;
        }


        /*
         * Szukamy selecta SORTUJ.
         */

        const sort=[
            ...document.querySelectorAll(
                "select"
            )
        ]
        .find(
            s=>
                [
                    ...s.options
                ]
                .some(
                    o=>
                        /najnowsze|snr|ocena/i.test(
                            o.textContent
                            ||
                            ""
                        )
                )
        );


        if(!sort){
            return;
        }


        const button=
            document.createElement(
                "button"
            );


        button.id=
            "mrRefreshNow";

        button.type=
            "button";

        button.textContent=
            "↻ Odśwież teraz";


        const age=
            document.createElement(
                "span"
            );


        age.id=
            "mrRefreshAge";

        age.textContent=
            "auto 5 min";


        sort.insertAdjacentElement(
            "afterend",
            button
        );


        button.insertAdjacentElement(
            "afterend",
            age
        );


        button.addEventListener(
            "click",
            ()=>doRefresh(true)
        );
    }


    installButton();


    setTimeout(
        installButton,
        500
    );


    /*
     * Jeden właściwy timer 5-minutowy.
     *
     * force=false — więc nawet jeśli jakiś stary
     * kod spróbuje odświeżyć chwilę wcześniej,
     * blokada wewnątrz refreshDetections()
     * nie dopuści do częstego redraw.
     */

    setInterval(
        ()=>doRefresh(false),
        FIVE_MINUTES
    );


    console.log(
        "MeteorRadio detections refresh = 5 min"
    );

})();

</script>



<script>
/* MR_SMART_QUEUE_COUNTER_V3 */

(function(){

    const STATUS_PORT = 8095;
    const POLL_MS = 10000;

    let pollTimer = null;
    let busy = false;

    let lastDetectionRefresh =
        Number(
            window.__mrLastDetectionRefresh
            ||
            0
        );


    function findPlace(){

        let el =
            document.getElementById(
                'mr-queue-remaining'
            );

        if(el){
            return el;
        }


        const walker =
            document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT
            );


        let node;

        while(
            node = walker.nextNode()
        ){

            const value =
                node.nodeValue || '';

            if(
                value.includes(
                    'auto 5 min'
                )
            ){

                const span =
                    document.createElement(
                        'span'
                    );

                span.id =
                    'mr-queue-remaining';

                span.style.marginLeft =
                    '7px';

                span.style.whiteSpace =
                    'nowrap';

                span.style.fontWeight =
                    '600';

                span.style.color =
                    '#d7a94a';

                span.textContent =
                    '· do oceny: …';


                const space =
                    document.createTextNode(
                        ' '
                    );

                node.parentNode.insertBefore(
                    space,
                    node.nextSibling
                );

                node.parentNode.insertBefore(
                    span,
                    space.nextSibling
                );

                return span;
            }
        }

        return null;
    }


    function stopPolling(){

        if(pollTimer !== null){

            clearTimeout(
                pollTimer
            );

            pollTimer = null;
        }
    }


    function schedulePolling(){

        stopPolling();

        pollTimer =
            setTimeout(
                function(){

                    refreshCounter(
                        false
                    );

                },
                POLL_MS
            );
    }


    async function refreshCounter(
        wake=false
    ){

        /*
         * Jeżeli request już trwa,
         * nie uruchamiamy drugiego.
         */
        if(busy){
            return;
        }

        busy = true;

        const el =
            findPlace();

        if(!el){
            busy = false;
            return;
        }


        try{

            const url =
                location.protocol
                +
                '//'
                +
                location.hostname
                +
                ':'
                +
                STATUS_PORT
                +
                '/status?t='
                +
                Date.now();


            const response =
                await fetch(
                    url,
                    {
                        cache: 'no-store'
                    }
                );


            if(!response.ok){

                throw new Error(
                    'HTTP '
                    +
                    response.status
                );
            }


            const data =
                await response.json();


            if(!data.ok){

                throw new Error(
                    data.error
                    ||
                    'status error'
                );
            }


            const remaining =
                Number(
                    data.remaining
                    ||
                    0
                );


            let suffix = '';


            if(
                data.state
                ===
                'paused'
            ){

                suffix =
                    ' · PAUZA';

                el.style.color =
                    '#f0ad4e';

            }else if(
                remaining === 0
            ){

                el.style.color =
                    '#59d987';

            }else{

                el.style.color =
                    '#d7a94a';

            }


            el.textContent =
                '· do oceny: '
                +
                remaining
                +
                suffix;


            el.title =
                'Ocenione: '
                +
                data.scored
                +
                ' / '
                +
                data.total
                +
                ' · bieżący cykl: '
                +
                data.done_cycle;


            /*
             * KLUCZOWA LOGIKA:
             *
             * > 0:
             * kolejna kontrola za 10 s.
             *
             * = 0:
             * żadnego kolejnego requestu.
             */
            if(remaining > 0){

                schedulePolling();

            }else{

                stopPolling();

            }


        }catch(err){

            console.debug(
                'MeteorRadio queue counter:',
                err
            );


            /*
             * Przy błędzie nie robimy agresywnego
             * retry-loopa.
             *
             * Jeżeli licznik był aktywny,
             * próbujemy ponownie za 10 s.
             */
            if(pollTimer !== null || wake){

                schedulePolling();
            }

        }finally{

            busy = false;
        }
    }


    /*
     * PIERWSZY ODCZYT
     */
    function initialStart(){

        refreshCounter(
            true
        );
    }


    if(
        document.readyState
        ===
        'loading'
    ){

        document.addEventListener(
            'DOMContentLoaded',
            initialStart,
            {
                once: true
            }
        );

    }else{

        initialStart();

    }


    /*
     * ==================================================
     * WAKE WATCHER
     * ==================================================
     *
     * To NIE odpytuje serwera.
     *
     * Co sekundę sprawdza wyłącznie lokalną
     * zmienną JS ustawianą przez refreshDetections().
     *
     * Gdy lista detekcji faktycznie się odświeży:
     *   wykonujemy JEDEN request do 8095.
     *
     * Jeśli pojawiły się nowe rekordy:
     *   polling 10 s uruchamia się ponownie.
     *
     * Jeśli dalej jest 0:
     *   polling pozostaje wyłączony.
     */

    setInterval(
        function(){

            const current =
                Number(
                    window.__mrLastDetectionRefresh
                    ||
                    0
                );


            if(
                current
                &&
                current
                !==
                lastDetectionRefresh
            ){

                lastDetectionRefresh =
                    current;


                /*
                 * Krótka zwłoka, żeby refreshDetections
                 * zdążył zakończyć synchronizację.
                 */
                setTimeout(
                    function(){

                        refreshCounter(
                            true
                        );

                    },
                    750
                );
            }

        },
        1000
    );


    /*
     * Dodatkowe wybudzenie po kliknięciu
     * "odśwież teraz".
     *
     * Nie jest wymagane do działania automatu,
     * ale zabezpiecza ręczny refresh.
     */

    document.addEventListener(
        'click',
        function(event){

            const target =
                event.target;

            if(!target){
                return;
            }

            const txt =
                String(
                    target.textContent
                    ||
                    ''
                ).toLowerCase();

            if(
                txt.includes(
                    'odśwież teraz'
                )
            ){

                setTimeout(
                    function(){

                        refreshCounter(
                            true
                        );

                    },
                    1500
                );
            }
        },
        true
    );


    /*
     * Debug z konsoli Firefoksa:
     *
     * window.mrQueueCounterStatus()
     */

    window.mrQueueCounterStatus =
        function(){

            return {
                polling:
                    pollTimer !== null,

                busy: busy,

                lastDetectionRefresh:
                    lastDetectionRefresh,

                intervalMs:
                    POLL_MS
            };
        };


    window.mrQueueCounterWake =
        function(){

            refreshCounter(
                true
            );
        };

})();

</script>





<script>
/* MR_READABLE_RESULTS_V1 */

(function(){

    function mrReadableResults(){

        const walker =
            document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT
            );

        const nodes = [];

        let node;

        while(
            node = walker.nextNode()
        ){

            const txt =
                node.nodeValue || '';

            if(
                /wyniki:\s*\d+\s*\/\s*\d+/i
                .test(txt)
            ){
                nodes.push(node);
            }
        }


        for(const n of nodes){

            let txt = n.nodeValue;


            txt = txt.replace(
                /wyniki:\s*(\d+)\s*\/\s*(\d+)/i,
                function(
                    all,
                    shown,
                    total
                ){

                    shown =
                        Number(shown);

                    total =
                        Number(total);


                    if(shown === total){

                        return (
                            'detekcje: '
                            +
                            total
                        );
                    }


                    return (
                        'widoczne: '
                        +
                        shown
                        +
                        ' z '
                        +
                        total
                    );
                }
            );


            /*
             * Samo "SNR ↓" / "Najnowsze"
             * staje się czytelniejszym:
             *
             * sort: SNR ↓
             */
            txt = txt.replace(
                /·\s*(SNR\s*[↓↑])/i,
                '· sort: $1'
            );

            txt = txt.replace(
                /·\s*(najnowsze|najstarsze)/i,
                '· sort: $1'
            );


            n.nodeValue = txt;
        }
    }


    /*
     * Pierwsze uruchomienie.
     */
    if(
        document.readyState === 'loading'
    ){

        document.addEventListener(
            'DOMContentLoaded',
            mrReadableResults,
            {
                once: true
            }
        );

    }else{

        mrReadableResults();
    }


    /*
     * Podpinamy się pod istniejące
     * refreshDetections().
     *
     * Bez MutationObserver.
     */
    const original =
        window.refreshDetections;


    if(
        typeof original === 'function'
    ){

        window.refreshDetections =
            async function(...args){

                const result =
                    await original.apply(
                        this,
                        args
                    );

                mrReadableResults();

                return result;
            };
    }


    /*
     * Sortowanie może zmienić podpis.
     * Nie wykonujemy requestów —
     * tylko poprawiamy lokalny tekst.
     */
    document.addEventListener(
        'change',
        function(){

            setTimeout(
                mrReadableResults,
                50
            );

        },
        true
    );


    window.mrReadableResults =
        mrReadableResults;

})();

</script>


<!-- MR_SORT_FINAL_8MODES_V2 -->

<script>

(() => {

    "use strict";


    /*
     * ======================================================
     * Metadata z systemu ulubionych na Raspberry Pi.
     *
     * /api/list zawiera:
     *   file
     *   score
     *   liked
     *
     * Najpierw próbujemy hostname, potem IPv4.
     * ======================================================
     */

    let mrSortMeta=
        new Map();


    function mrLikesBases(){

        return [
            "http://"
            +
            location.hostname
            +
            ":8096",

        ];
    }


    async function mrFetchJson(
        url,
        timeout=1800
    ){

        const controller=
            new AbortController();

        const timer=
            setTimeout(
                ()=>controller.abort(),
                timeout
            );


        try{

            const response=
                await fetch(
                    url,
                    {
                        cache:"no-store",
                        signal:controller.signal
                    }
                );


            if(!response.ok){

                throw new Error(
                    "HTTP "
                    +
                    response.status
                );
            }


            return await response.json();

        }finally{

            clearTimeout(
                timer
            );
        }
    }


    async function mrLoadSortMeta(){

        let lastError=null;


        for(
            const base
            of mrLikesBases()
        ){

            try{

                const data=
                    await mrFetchJson(
                        base
                        +
                        "/api/list?t="
                        +
                        Date.now()
                    );


                if(
                    !data
                    ||
                    data.ok
                    !==
                    true
                    ||
                    !Array.isArray(
                        data.items
                    )
                ){

                    throw new Error(
                        "bad likes API"
                    );
                }


                const next=
                    new Map();


                for(
                    const item
                    of data.items
                ){

                    if(
                        !item
                        ||
                        !item.file
                    ){
                        continue;
                    }


                    next.set(
                        String(
                            item.file
                        ),
                        {
                            score:
                                Number(
                                    item.score
                                ),

                            liked:
                                Boolean(
                                    item.liked
                                )
                        }
                    );
                }


                mrSortMeta=
                    next;


                window.__mrSortMeta=
                    mrSortMeta;


                console.log(
                    "MR SORT META:",
                    mrSortMeta.size,
                    "source:",
                    base
                );


                return true;

            }catch(error){

                lastError=
                    error;
            }
        }


        console.warn(
            "MR SORT META unavailable:",
            lastError
        );


        return false;
    }


    function mrFile(
        item
    ){

        return String(
            item?.file
            ??
            item?.filename
            ??
            item?.name
            ??
            ""
        );
    }


    function mrTime(
        item
    ){

        const candidates=[
            item?.time,
            item?.timestamp,
            item?.datetime,
            item?.created_at,
            item?.mtime
        ];


        for(
            const value
            of candidates
        ){

            if(
                value === null
                ||
                value === undefined
                ||
                value === ""
            ){
                continue;
            }


            const numeric=
                Number(
                    value
                );


            if(
                Number.isFinite(
                    numeric
                )
                &&
                numeric > 1000000
            ){

                return (
                    numeric < 100000000000
                    ?
                    numeric*1000
                    :
                    numeric
                );
            }


            const parsed=
                Date.parse(
                    String(value)
                    .replace(
                        " ",
                        "T"
                    )
                );


            if(
                Number.isFinite(
                    parsed
                )
            ){

                return parsed;
            }
        }


        /*
         * Fallback z nazwy:
         *
         * SMP_143050000_20260918_143552_....
         */

        const file=
            mrFile(
                item
            );


        const m=
            file.match(
                /_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_/
            );


        if(m){

            return Date.UTC(
                Number(m[1]),
                Number(m[2])-1,
                Number(m[3]),
                Number(m[4]),
                Number(m[5]),
                Number(m[6])
            );
        }


        return 0;
    }


    function mrSNR(
        item
    ){

        const values=[
            item?.snr_db,
            item?.snr,
            item?.SNR,
            item?.peak_snr,
            item?.peakSnr
        ];


        for(
            const value
            of values
        ){

            const n=
                Number(
                    value
                );


            if(
                Number.isFinite(
                    n
                )
            ){

                return n;
            }
        }


        return null;
    }


    function mrScore(
        item
    ){

        const file=
            mrFile(
                item
            );


        const meta=
            mrSortMeta.get(
                file
            );


        if(
            meta
            &&
            Number.isFinite(
                Number(
                    meta.score
                )
            )
        ){

            return Number(
                meta.score
            );
        }


        const direct=[
            item?.score,
            item?.quality_score,
            item?.classification_score
        ];


        for(
            const value
            of direct
        ){

            const n=
                Number(
                    value
                );


            if(
                Number.isFinite(n)
            ){

                return n;
            }
        }


        /*
         * Fallback zgodny ze starym systemem.
         */

        const keys=[
            "meteorradio-v562-point-classifications",
            "meteorradio-v56-classifications"
        ];


        for(
            const key
            of keys
        ){

            try{

                const obj=
                    JSON.parse(
                        localStorage.getItem(
                            key
                        )
                        ||
                        "{}"
                    );


                const value=
                    obj[
                        file
                    ];


                const n=
                    Number(
                        value?.score
                        ??
                        value?.confidence
                    );


                if(
                    Number.isFinite(
                        n
                    )
                ){

                    return n;
                }

            }catch(_){
            }
        }


        return null;
    }


    function mrLiked(
        item
    ){

        const meta=
            mrSortMeta.get(
                mrFile(item)
            );


        return Boolean(
            meta
            &&
            meta.liked
        );
    }


    function mrNewestTie(
        a,
        b
    ){

        return (
            mrTime(b)
            -
            mrTime(a)
        );
    }


    function mrCompareNumber(
        a,
        b,
        descending
    ){

        const aOK=
            Number.isFinite(a);

        const bOK=
            Number.isFinite(b);


        /*
         * Brak wartości zawsze na końcu.
         */

        if(
            !aOK
            &&
            !bOK
        ){
            return 0;
        }


        if(!aOK){
            return 1;
        }


        if(!bOK){
            return -1;
        }


        return (
            descending
            ?
            b-a
            :
            a-b
        );
    }


    function mrFinalSort(
        data
    ){

        const out=
            Array.isArray(
                data
            )
            ?
            [...data]
            :
            [];


        let mode=
            "newest";


        try{

            mode=
                document
                .getElementById(
                    "v55DetectionSort"
                )
                ?.value
                ||
                v55SortMode
                ||
                "newest";

        }catch(_){
        }


        switch(
            mode
        ){


            case "oldest":

                out.sort(
                    (a,b)=>
                        mrTime(a)
                        -
                        mrTime(b)
                );

                break;


            case "snr_desc":

                out.sort(
                    (a,b)=>
                        mrCompareNumber(
                            mrSNR(a),
                            mrSNR(b),
                            true
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "snr_asc":

                out.sort(
                    (a,b)=>
                        mrCompareNumber(
                            mrSNR(a),
                            mrSNR(b),
                            false
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "liked_first":

                out.sort(
                    (a,b)=>
                        (
                            Number(
                                mrLiked(b)
                            )
                            -
                            Number(
                                mrLiked(a)
                            )
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "unliked_first":

                out.sort(
                    (a,b)=>
                        (
                            Number(
                                mrLiked(a)
                            )
                            -
                            Number(
                                mrLiked(b)
                            )
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "score_desc":

                out.sort(
                    (a,b)=>
                        mrCompareNumber(
                            mrScore(a),
                            mrScore(b),
                            true
                        )
                        ||
                        mrCompareNumber(
                            mrSNR(a),
                            mrSNR(b),
                            true
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "score_asc":

                out.sort(
                    (a,b)=>
                        mrCompareNumber(
                            mrScore(a),
                            mrScore(b),
                            false
                        )
                        ||
                        mrCompareNumber(
                            mrSNR(a),
                            mrSNR(b),
                            true
                        )
                        ||
                        mrNewestTie(
                            a,
                            b
                        )
                );

                break;


            case "newest":
            default:

                out.sort(
                    (a,b)=>
                        mrTime(b)
                        -
                        mrTime(a)
                );

                break;
        }


        return out;
    }


    function mrInstallEngine(){

        try{

            window.v55SortData=
                mrFinalSort;

        }catch(_){
        }


        try{

            v55SortData=
                mrFinalSort;

        }catch(_){
        }
    }


    function mrFindSort(){

        return (
            document.getElementById(
                "v55DetectionSort"
            )
            ||
            [
                ...document.querySelectorAll(
                    "select"
                )
            ]
            .find(
                select=>
                    [
                        ...select.options
                    ]
                    .some(
                        option=>
                            option.value
                            ===
                            "score_desc"
                    )
            )
        );
    }


    function mrInstallMenu(){

        const select=
            mrFindSort();


        if(!select){

            console.warn(
                "MR SORT: select not found"
            );

            return;
        }


        const allowed=[
            "newest",
            "oldest",
            "snr_desc",
            "snr_asc",
            "liked_first",
            "unliked_first",
            "score_desc",
            "score_asc"
        ];


        const oldValue=
            allowed.includes(
                select.value
            )
            ?
            select.value
            :
            "newest";


        select.innerHTML=`
<option value="newest">Najnowsze</option>
<option value="oldest">Najstarsze</option>
<option value="snr_desc">SNR ↓</option>
<option value="snr_asc">SNR ↑</option>
<option value="liked_first">Polubiane</option>
<option value="unliked_first">Niepolubiane</option>
<option value="score_desc">OCENA ↓</option>
<option value="score_asc">OCENA ↑</option>
`;


        select.value=
            oldValue;


        if(
            select.dataset
            .mrSortV2Installed
            ===
            "1"
        ){

            return;
        }


        select.dataset
        .mrSortV2Installed=
            "1";


        select.addEventListener(
            "change",
            async ()=>{

                try{

                    v55SortMode=
                        select.value;

                }catch(_){
                }


                /*
                 * Dla ocen i ulubionych zawsze
                 * pobieramy najnowszy stan z Pi.
                 */

                if(
                    [
                        "liked_first",
                        "unliked_first",
                        "score_desc",
                        "score_asc"
                    ]
                    .includes(
                        select.value
                    )
                ){

                    await mrLoadSortMeta();
                }


                try{

                    if(
                        typeof detectionPage
                        !==
                        "undefined"
                    ){

                        detectionPage=1;
                    }


                    if(
                        typeof renderDetectionList
                        ===
                        "function"
                        &&
                        typeof detectionsCache
                        !==
                        "undefined"
                    ){

                        renderDetectionList(
                            detectionsCache
                        );
                    }

                }catch(error){

                    console.warn(
                        "MR SORT render:",
                        error
                    );
                }

            }
        );
    }


    async function mrInit(){

        mrInstallEngine();

        mrInstallMenu();

        await mrLoadSortMeta();


        try{

            if(
                typeof renderDetectionList
                ===
                "function"
                &&
                typeof detectionsCache
                !==
                "undefined"
            ){

                renderDetectionList(
                    detectionsCache
                );
            }

        }catch(_){
        }
    }


    /*
     * Skrypt znajduje się przy końcu BODY,
     * więc wykonujemy od razu.
     */

    mrInstallEngine();

    mrInstallMenu();


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            mrInit,
            {
                once:true
            }
        );

    }else{

        mrInit();
    }


    /*
     * Brak MutationObserver.
     * Brak dodatkowego setInterval.
     */

    window.mrReloadSortMeta=
        mrLoadSortMeta;

})();

</script>


<!-- MR_GLOBAL_SORT_CONTROLS_V1 -->

<script>

(() => {

    "use strict";


    function setup(){

        const prev=
            document.getElementById(
                "detPrev"
            );


        const next=
            document.getElementById(
                "detNext"
            );


        const sort=
            document.getElementById(
                "v55DetectionSort"
            );


        if(
            prev
            &&
            prev.dataset.mrGlobalPager
            !==
            "1"
        ){

            prev.dataset.mrGlobalPager=
                "1";


            prev.addEventListener(
                "click",
                event=>{

                    event.preventDefault();

                    event.stopPropagation();

                    event.stopImmediatePropagation();


                    if(
                        detectionPage
                        >
                        1
                    ){

                        detectionPage--;

                        selectedDetectionFile=
                            null;


                        (typeof v53ApplyFilter === "function" ? v53ApplyFilter() : refreshDetections(true)); /* MR_PAGER_V53_BRIDGE_V1 */
                    }

                },
                true
            );
        }


        if(
            next
            &&
            next.dataset.mrGlobalPager
            !==
            "1"
        ){

            next.dataset.mrGlobalPager=
                "1";


            next.addEventListener(
                "click",
                event=>{

                    event.preventDefault();

                    event.stopPropagation();

                    event.stopImmediatePropagation();


                    if(
                        detectionPage
                        <
                        detectionTotalPages
                    ){

                        detectionPage++;

                        selectedDetectionFile=
                            null;


                        (typeof v53ApplyFilter === "function" ? v53ApplyFilter() : refreshDetections(true)); /* MR_PAGER_V53_BRIDGE_V1 */
                    }

                },
                true
            );
        }


        if(
            sort
            &&
            sort.dataset.mrGlobalSort
            !==
            "1"
        ){

            sort.dataset.mrGlobalSort=
                "1";


            sort.addEventListener(
                "change",
                async event=>{

                    event.stopPropagation();

                    event.stopImmediatePropagation();


                    try{

                        v55SortMode=
                            sort.value;

                    }catch(_){
                    }


                    detectionPage=
                        1;


                    selectedDetectionFile=
                        null;


                    if(
                        [
                            "liked_first",
                            "unliked_first",
                            "score_desc",
                            "score_asc"
                        ].includes(
                            sort.value
                        )
                        &&
                        typeof window.mrReloadSortMeta
                        ===
                        "function"
                    ){

                        try{

                            await window.mrReloadSortMeta();

                        }catch(_){
                        }
                    }


                    if(
                        Array.isArray(
                            window
                            .__mrGlobalDetectionsAll
                        )
                    ){

                        (typeof v53ApplyFilter === "function" ? v53ApplyFilter() : refreshDetections(true)); /* MR_PAGER_V53_BRIDGE_V1 */

                    }else{

                        await refreshDetections(
                            true
                        );
                    }

                },
                true
            );
        }
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            setup,
            {
                once:true
            }
        );

    }else{

        setup();
    }

})();

</script>


<!-- MR_PI_LIKES_STARS_SYNC_V1 -->

<script>

(() => {

    "use strict";


    /*
     * Jedno źródło prawdy:
     *
     * Raspberry Pi / port 8096.
     *
     * Stary localStorage Firefoksa nie decyduje
     * już o stanie wizualnym gwiazdki.
     */


    function mrLikeMeta(){

        return (
            window.__mrSortMeta
            instanceof Map
        )
        ?
        window.__mrSortMeta
        :
        new Map();
    }


    function mrIsPiLiked(
        file
    ){

        const meta=
            mrLikeMeta()
            .get(
                String(
                    file
                    ||
                    ""
                )
            );


        return Boolean(
            meta
            &&
            meta.liked
        );
    }


    function mrSyncPiStars(){

        const meta=
            mrLikeMeta();


        document
        .querySelectorAll(
            ".v53-star[data-star]"
        )
        .forEach(
            star=>{

                const file=
                    String(
                        star.dataset.star
                        ||
                        ""
                    );


                const info=
                    meta.get(
                        file
                    );


                const liked=
                    Boolean(
                        info
                        &&
                        info.liked
                    );


                star.textContent=
                    liked
                    ?
                    "★"
                    :
                    "☆";


                star.classList.toggle(
                    "on",
                    liked
                );


                star.setAttribute(
                    "aria-pressed",
                    liked
                    ?
                    "true"
                    :
                    "false"
                );


                star.title=
                    liked
                    ?
                    "Usuń z ulubionych na Pi"
                    :
                    "Dodaj do ulubionych na Pi";
            }
        );
    }


    window.mrSyncPiStars=
        mrSyncPiStars;


    /*
     * Po każdym renderowaniu listy
     * nadpisujemy stan starego localStorage
     * stanem z 8096.
     */

    if(
        typeof window.renderDetectionList
        ===
        "function"
        &&
        !window.renderDetectionList
        .__mrPiStarsWrapped
    ){

        const original=
            window.renderDetectionList;


        const wrapped=
            function(...args){

                const result=
                    original.apply(
                        this,
                        args
                    );


                queueMicrotask(
                    mrSyncPiStars
                );


                return result;
            };


        wrapped.__mrPiStarsWrapped=
            true;


        window.renderDetectionList=
            wrapped;


        try{

            renderDetectionList=
                wrapped;

        }catch(_){
        }
    }


    /*
     * Globalny pager też kończymy synchronizacją.
     */

    if(
        typeof window.mrRenderGlobalDetectionPage
        ===
        "function"
        &&
        !window.mrRenderGlobalDetectionPage
        .__mrPiStarsWrapped
    ){

        const originalGlobal=
            window.mrRenderGlobalDetectionPage;


        const wrappedGlobal=
            function(...args){

                const result=
                    originalGlobal.apply(
                        this,
                        args
                    );


                queueMicrotask(
                    mrSyncPiStars
                );


                return result;
            };


        wrappedGlobal.__mrPiStarsWrapped=
            true;


        window.mrRenderGlobalDetectionPage=
            wrappedGlobal;
    }


    function mrLikesBases(){

        return [
            "http://"
            +
            location.hostname
            +
            ":8096",

        ];
    }


    async function mrTogglePiLike(
        file
    ){

        let lastError=null;


        for(
            const base
            of mrLikesBases()
        ){

            try{

                const controller=
                    new AbortController();


                const timer=
                    setTimeout(
                        ()=>controller.abort(),
                        1800
                    );


                let response;


                try{

                    response=
                        await fetch(
                            base
                            +
                            "/api/toggle?file="
                            +
                            encodeURIComponent(
                                file
                            ),
                            {
                                method:"POST",
                                cache:"no-store",
                                signal:
                                    controller.signal
                            }
                        );

                }finally{

                    clearTimeout(
                        timer
                    );
                }


                const data=
                    await response.json();


                if(
                    !response.ok
                    ||
                    !data.ok
                ){

                    throw new Error(
                        data.error
                        ||
                        (
                            "HTTP "
                            +
                            response.status
                        )
                    );
                }


                return data;

            }catch(error){

                lastError=
                    error;
            }
        }


        throw (
            lastError
            ||
            new Error(
                "8096 unavailable"
            )
        );
    }


    /*
     * CAPTURE:
     *
     * przechwytujemy kliknięcie zanim dojdzie
     * do starego handlera zapisującego localStorage.
     */

    document.addEventListener(
        "click",
        async event=>{

            const star=
                event.target.closest(
                    ".v53-star[data-star]"
                );


            if(!star){

                return;
            }


            event.preventDefault();

            event.stopPropagation();

            event.stopImmediatePropagation();


            const file=
                String(
                    star.dataset.star
                    ||
                    ""
                );


            if(!file){

                return;
            }


            star.disabled=
                true;


            try{

                const data=
                    await mrTogglePiLike(
                        file
                    );


                const map=
                    mrLikeMeta();


                const old=
                    map.get(
                        file
                    )
                    ||
                    {};


                map.set(
                    file,
                    {
                        ...old,
                        liked:
                            Boolean(
                                data.liked
                            )
                    }
                );


                window.__mrSortMeta=
                    map;


                mrSyncPiStars();


                /*
                 * Gdy sortujemy po polubieniach,
                 * rekord od razu zmienia miejsce.
                 */

                const sort=
                    document.getElementById(
                        "v55DetectionSort"
                    );


                if(
                    sort
                    &&
                    (
                        sort.value
                        ===
                        "liked_first"
                        ||
                        sort.value
                        ===
                        "unliked_first"
                    )
                    &&
                    typeof window
                    .mrRenderGlobalDetectionPage
                    ===
                    "function"
                ){

                    window
                    .mrRenderGlobalDetectionPage();
                }


            }catch(error){

                console.error(
                    "MR PI LIKE:",
                    error
                );


                alert(
                    "Nie udało się zapisać "
                    +
                    "polubienia na Raspberry Pi."
                );


            }finally{

                star.disabled=
                    false;
            }

        },
        true
    );


    async function mrInitialPiStars(){

        /*
         * Załaduj aktualny stan 8096,
         * także jeżeli sort = Najnowsze.
         */

        if(
            typeof window.mrReloadSortMeta
            ===
            "function"
        ){

            try{

                await window
                .mrReloadSortMeta();

            }catch(error){

                console.warn(
                    "MR initial likes:",
                    error
                );
            }
        }


        mrSyncPiStars();
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            mrInitialPiStars,
            {
                once:true
            }
        );

    }else{

        mrInitialPiStars();
    }


})();

</script>


<!-- MR_REMOVE_STATS_FROM_8094_V1 -->
<style>
#v59StatsModal{
    display:none !important;
}
</style>

<script>
(function(){

    function mrRemoveOldStats(){

        try{

            document
            .querySelectorAll(
                "button,a"
            )
            .forEach(
                el=>{

                    const text=
                        (
                            el.textContent
                            ||
                            ""
                        )
                        .trim()
                        .toUpperCase();

                    if(
                        text
                        ===
                        "STATYSTYKA"
                    ){
                        el.remove();
                    }
                }
            );


            const modal=
                document.getElementById(
                    "v59StatsModal"
                );

            if(modal){
                modal.remove();
            }

        }catch(e){}
    }


    if(
        document.readyState
        ===
        "loading"
    ){

        document.addEventListener(
            "DOMContentLoaded",
            ()=>{
                mrRemoveOldStats();

                setTimeout(
                    mrRemoveOldStats,
                    250
                );

                setTimeout(
                    mrRemoveOldStats,
                    1200
                );
            },
            {
                once:true
            }
        );

    }else{

        mrRemoveOldStats();

        setTimeout(
            mrRemoveOldStats,
            250
        );

        setTimeout(
            mrRemoveOldStats,
            1200
        );
    }

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
        *args,
    ):
        return


    def send_bytes(
        self,
        code,
        data,
        content_type,
    ):

        self.send_response(
            code
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Cache-Control",
            "no-store, "
            "no-cache, "
            "must-revalidate",
        )

        self.send_header(
            "Content-Length",
            str(
                len(data)
            ),
        )

        self.end_headers()

        self.wfile.write(
            data
        )


    def send_json(
        self,
        payload,
        code=200,
    ):

        raw = json.dumps(
            payload,
            separators=(",",":"),
        ).encode(
            "utf-8"
        )

        self.send_bytes(
            code,
            raw,
            "application/json; "
            "charset=utf-8",
        )


    def find_smp(
        self,
        basename,
    ):

        if Path(
            basename
        ).name != basename:

            return None

        if not re.match(
            r"^SMP_\d+_"
            r"\d{8}_"
            r"\d{6}_"
            r"\d{6}\.npz$",
            basename,
        ):

            return None

        try:

            for path in RADAR_DATA.rglob(
                basename
            ):

                if path.is_file():

                    return path

        except Exception:

            pass

        return None


    def detection_png(
        self,
        basename,
    ):

        src = self.find_smp(
            basename
        )

        if src is None:

            self.send_json(
                {
                    "ok":False,
                    "error":"not found",
                },
                404,
            )

            return

        CACHE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        dst = (
            CACHE_DIR
            / (
                src.stem
                + ".png"
            )
        )

        with RENDER_LOCK:

            if not dst.exists():

                try:

                    subprocess.run(
                        [
                            str(
                                VENVPY
                            ),
                            str(
                                RENDERER
                            ),
                            str(
                                src
                            ),
                            str(
                                dst
                            ),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=35,
                    )

                except Exception as e:

                    self.send_json(
                        {
                            "ok":False,
                            "error":
                                str(e),
                        },
                        500,
                    )

                    return

        try:

            raw = dst.read_bytes()

        except Exception:

            self.send_json(
                {
                    "ok":False,
                    "error":
                        "render failed",
                },
                500,
            )

            return

        self.send_bytes(
            200,
            raw,
            "image/png",
        )



    def detection_v5_png(
        self,
        basename,
        maxhold=True,
    ):

        """
        V5.2 LIGHT

        Render tylko na żądanie.
        Jeden renderer jednocześnie.
        Wynik trafia do cache.

        Nie korzysta z live waterfallu
        ani nie otwiera RTL-SDR.
        """

        import subprocess
        import threading

        from pathlib import Path as _Path


        src = self.find_smp(
            basename
        )


        if src is None:

            self.send_json(
                {
                    "ok": False,
                    "error": "not found",
                },
                404,
            )

            return


        cache_dir = _Path(
            "/home/pi/meteorradio-web/cache"
        )

        cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


        renderer = _Path(
            "/home/pi/meteorradio-web/"
            "render_detection_v5.py"
        )


        mh = (
            "1"
            if maxhold
            else "0"
        )


        dst = (
            cache_dir
            /
            (
                src.stem
                +
                "_v52_mh"
                +
                mh
                +
                ".png"
            )
        )


        #
        # Jeden renderer matplotlib jednocześnie.
        #
        # ThreadingHTTPServer może dostać kilka
        # requestów naraz. Nie chcemy wtedy
        # odpalać dwóch dużych FFT/renderów.
        #

        if not hasattr(
            self.server,
            "_v52_render_lock",
        ):

            self.server._v52_render_lock = (
                threading.Lock()
            )


        lock = (
            self.server._v52_render_lock
        )


        try:

            with lock:

                need_render = (
                    not dst.exists()
                )


                if not need_render:

                    try:

                        need_render = (
                            dst.stat().st_mtime
                            <
                            max(
                                src.stat().st_mtime,
                                renderer.stat().st_mtime,
                            )
                        )

                    except Exception:

                        need_render = True


                if need_render:

                    proc = subprocess.run(
                        [
                            "/usr/bin/nice",
                            "-n",
                            "12",
                            "/home/pi/vMeteorRadio/bin/python",
                            str(renderer),
                            str(src),
                            str(dst),
                            mh,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=90,
                    )


                    if proc.returncode != 0:

                        self.send_json(
                            {
                                "ok": False,
                                "error":
                                    (
                                        proc.stderr
                                        or
                                        "renderer failed"
                                    )[-1500:],
                            },
                            500,
                        )

                        return


                if (
                    not dst.exists()
                    or
                    dst.stat().st_size < 1000
                ):

                    self.send_json(
                        {
                            "ok": False,
                            "error":
                                "renderer nie utworzył "
                                "poprawnego PNG",
                        },
                        500,
                    )

                    return


                data = dst.read_bytes()


                if not data.startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):

                    self.send_json(
                        {
                            "ok": False,
                            "error":
                                "niepoprawny format "
                                "pliku renderera",
                        },
                        500,
                    )

                    return


        except subprocess.TimeoutExpired:

            self.send_json(
                {
                    "ok": False,
                    "error":
                        "renderer przekroczył "
                        "90 sekund",
                },
                504,
            )

            return


        except Exception as e:

            self.send_json(
                {
                    "ok": False,
                    "error":
                        "V5 renderer exception: "
                        +
                        repr(e),
                },
                500,
            )

            return


        try:

            self.send_bytes(
                200,
                data,
                "image/png",
            )

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):

            #
            # Klient zamknął kartę / zmienił
            # detekcję podczas renderowania.
            # Nie jest to awaria serwera.
            #
            return



    def detection_v5_classification(
        self,
        basename,
    ):

        import json as _json
        import subprocess
        import sys

        from pathlib import Path as _Path


        src = self.find_smp(
            basename
        )


        if src is None:

            self.send_json(
                {
                    "ok": False,
                    "error": "not found",
                },
                404,
            )

            return


        cache_dir = _Path(
            "/home/pi/meteorradio-web/cache"
        )

        cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


        classifier = _Path(
            "/home/pi/meteorradio-web/"
            "classify_detection_v5.py"
        )


        dst = (
            cache_dir
            /
            (
                src.stem
                +
                "_v5_class.json"
            )
        )


        need = (
            not dst.exists()
        )


        if not need:

            try:

                need = (
                    dst.stat().st_mtime
                    <
                    max(
                        src.stat().st_mtime,
                        classifier.stat().st_mtime,
                    )
                )

            except Exception:

                need = True


        if need:

            proc = subprocess.run(
                [
                    "/usr/bin/nice",
                    "-n",
                    "15",
                    "/home/pi/vMeteorRadio/bin/python",

                    str(
                        classifier
                    ),
                    str(
                        src
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=45,
            )


            if (
                proc.returncode
                != 0
            ):

                self.send_json(
                    {
                        "ok": False,
                        "error":
                            (
                                proc.stderr
                                or
                                "classifier failed"
                            )[-1000:],
                    },
                    500,
                )

                return


            text = (
                proc.stdout
                .strip()
            )

            #
            # Walidacja JSON przed cache.
            #
            _json.loads(
                text
            )

            dst.write_text(
                text,
                encoding="utf-8",
            )


        try:

            payload = _json.loads(
                dst.read_text(
                    encoding="utf-8"
                )
            )

        except Exception as e:

            payload = {
                "ok": False,
                "error": repr(
                    e
                ),
            }


        self.send_json(
            payload
        )



    def do_GET(
        self,
    ):

        parsed = urlparse(
            self.path
        )

        path = parsed.path

        query = parse_qs(
            parsed.query
        )


        if path == "/api/waterfall-history":

            from v5_features import (
                history_data,
            )

            self.send_json(
                history_data()
            )

            return


        if path == "/api/stats":

            self.send_json(
                v5_stats_data()
            )

            return


        # V562_SCORE_INDEX_ENDPOINT
        if path == "/api/score-index":

            import json as _json

            from pathlib import Path as _Path


            score_path = _Path(
                '/home/pi/meteorradio-web/cache/v562_score_index.json'
            )


            try:

                payload = _json.loads(
                    score_path.read_text(
                        encoding="utf-8"
                    )
                )

            except Exception:

                payload = {
                    "ok": True,
                    "version": "v562-score-index-1",
                    "count": 0,
                    "scores": {},
                }


            self.send_json(
                payload
            )

            return


        # V562_PERFORMANCE_GUARD_BACKEND
        #
        # Ciężką klasyfikację wolno uruchomić
        # wyłącznie nowemu detail loaderowi V5.6.2.
        #
        # Stary frontend V5.5/V5.6 potrafił
        # odpalić analizę setek plików po użyciu
        # filtra/procentowego PRZELICZ.
        #
        if path == "/api/classification":

            request_version = query.get(
                "v",
                [""],
            )[0]


            if request_version != "562p1":

                self.send_json(
                    {
                        "ok": False,
                        "deferred": True,
                        "error":
                            (
                                "bulk classification disabled; "
                                "open detection for point score"
                            ),
                    },
                    429,
                )

                return


            basename = query.get(
                "file",
                [""],
            )[0]


            self.detection_v5_classification(
                basename
            )

            return


        if path == "/detection-v5.png":

            basename = query.get(
                "file",
                [""],
            )[0]

            mh = query.get(
                "maxhold",
                ["1"],
            )[0]

            self.detection_v5_png(
                basename,
                maxhold=(
                    str(
                        mh
                    )
                    != "0"
                ),
            )

            return


        if path == "/api/live":

            self.send_json(
                live_data()
            )

            return


        if path == "/api/status":

            self.send_json(
                health_data()
            )

            return


        if path == "/api/detections":

            try:

                limit = int(
                    query.get(
                        "limit",
                        ["8"],
                    )[0]
                )

            except Exception:

                limit = 8

            # MR_DETECTIONS_LIMIT_5000_V1
            limit = max(
                1,
                min(
                    limit,
                    5000,
                )
            )

            try:

                page = int(
                    query.get(
                        "page",
                        ["1"],
                    )[0]
                )

            except Exception:

                page = 1

            page = max(
                1,
                page,
            )

            self.send_json(
                detection_data(
                    limit=limit,
                    page=page,
                )
            )

            return


        if path == "/detection.png":

            basename = query.get(
                "file",
                [""],
            )[0]

            self.detection_png(
                basename
            )

            return


        if path in (
            "/",
            "/index.html",
        ):

            self.send_bytes(
                200,
                HTML.encode(
                    "utf-8"
                ),
                "text/html; "
                "charset=utf-8",
            )

            return


        self.send_json(
            {
                "ok":False,
                "error":"Not found",
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
        "MeteorRadio Dashboard V2: "
        f"http://{HOST}:{PORT}/",
        flush=True,
    )

    server.serve_forever()
