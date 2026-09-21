#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

from datetime import datetime, timezone
from pathlib import Path


OUTDIR = Path("/home/pi/meteorradio-web/health")

LATEST_JSON = OUTDIR / "latest.json"
LATEST_TXT = OUTDIR / "latest.txt"
HISTORY = OUTDIR / "history.jsonl"

RADAR = Path("/home/pi/radar_data")

MAX_HISTORY_LINES = 3000


SERVICES = [
    "meteorradio.service",
    "meteorradio-web.service",
    "meteorradio-likes.service",
    "meteorradio-queue-status.service",
    "meteorradio-score-new.service",
    "meteorradio-score-new.timer",
    "meteorradio-prerender.service",
    "meteorradio-retention.timer",
    "meteorradio-stats.service",
    "meteorradio-3d.service",
    "meteorradio-trajectory.service",
]


def run(cmd, timeout=8):

    try:

        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )

        return {
            "rc": p.returncode,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
        }

    except Exception as e:

        return {
            "rc": -1,
            "stdout": "",
            "stderr": repr(e),
        }


def systemd_state(unit):

    r = run(
        [
            "systemctl",
            "show",
            unit,
            "-p", "ActiveState",
            "-p", "SubState",
            "-p", "MainPID",
            "-p", "ExecMainStartTimestamp",
            "-p", "ExecMainExitTimestamp",
        ]
    )

    result = {}

    for line in r["stdout"].splitlines():

        if "=" not in line:
            continue

        k, v = line.split("=", 1)

        result[k] = v

    result["rc"] = r["rc"]

    return result


def http_get(url, expect_json=False):

    started = time.monotonic()

    try:

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "MeteorRadio-HealthCheck/1.0"
            },
        )

        with urllib.request.urlopen(
            req,
            timeout=5,
        ) as resp:

            body = resp.read()

            elapsed = (
                time.monotonic()
                - started
            )

            result = {
                "ok": 200 <= resp.status < 300,
                "http": resp.status,
                "seconds": round(elapsed, 4),
                "bytes": len(body),
            }

            if expect_json:

                try:
                    result["json"] = json.loads(
                        body.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
                except Exception as e:
                    result["json_error"] = repr(e)

            return result

    except Exception as e:

        return {
            "ok": False,
            "http": None,
            "seconds": round(
                time.monotonic()
                - started,
                4,
            ),
            "error": repr(e),
        }


def temperature():

    r = run(
        [
            "vcgencmd",
            "measure_temp",
        ]
    )

    m = re.search(
        r"temp=([0-9.]+)",
        r["stdout"],
    )

    if not m:
        return None

    return float(
        m.group(1)
    )


def throttled():

    r = run(
        [
            "vcgencmd",
            "get_throttled",
        ]
    )

    m = re.search(
        r"0x([0-9a-fA-F]+)",
        r["stdout"],
    )

    if not m:

        return {
            "raw": r["stdout"],
            "value": None,
            "active_bits": None,
            "historical_bits": None,
        }

    value = int(
        m.group(1),
        16,
    )

    return {
        "raw": r["stdout"],
        "value": value,
        "hex": hex(value),

        # bity 0..3 = stan bieżący
        "active_bits": value & 0xF,

        # bity 16..19 = historia
        "historical_bits":
            (value >> 16) & 0xF,
    }


def zombie_processes():

    zombies = []

    proc = Path("/proc")

    for p in proc.iterdir():

        if not p.name.isdigit():
            continue

        try:

            stat = (
                p / "stat"
            ).read_text(
                errors="replace"
            )

            parts = stat.split()

            if len(parts) < 4:
                continue

            state = parts[2]

            if state != "Z":
                continue

            pid = int(
                p.name
            )

            ppid = int(
                parts[3]
            )

            try:

                cmd = (
                    p / "cmdline"
                ).read_bytes().replace(
                    b"\0",
                    b" ",
                ).decode(
                    errors="replace"
                ).strip()

            except Exception:
                cmd = ""

            if not cmd:
                cmd = parts[1]

            zombies.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "cmd": cmd,
                }
            )

        except Exception:
            pass

    return zombies


def radar_stats():

    count = 0
    total_bytes = 0

    try:

        for p in RADAR.rglob(
            "SMP_*.npz"
        ):

            try:
                st = p.stat()
            except Exception:
                continue

            count += 1
            total_bytes += st.st_size

    except Exception:
        pass

    return {
        "smp_count": count,
        "bytes": total_bytes,
        "mib": round(
            total_bytes
            / 1024
            / 1024,
            2,
        ),
    }


def recent_kernel_events():

    r = run(
        [
            "journalctl",
            "-k",
            "--since",
            "-35 minutes",
            "--no-pager",
            "-o",
            "cat",
        ],
        timeout=10,
    )

    if r["rc"] != 0:

        return {
            "available": False,
            "error": r["stderr"],
            "events": [],
        }

    pattern = re.compile(
        r"("
        r"under.?voltage|"
        r"voltage.*low|"
        r"out of memory|"
        r"\boom\b|"
        r"rtl.*(?:error|disconnect)|"
        r"usb.*(?:error|reset|disconnect)"
        r")",
        re.I,
    )

    events = []

    for line in r["stdout"].splitlines():

        if pattern.search(line):

            events.append(
                line[:500]
            )

    return {
        "available": True,
        "count": len(events),
        "events": events[-20:],
    }


def severity_rank(level):

    return {
        "OK": 0,
        "WARN": 1,
        "CRIT": 2,
    }.get(
        level,
        0,
    )


def main():

    OUTDIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now(
        timezone.utc
    ).astimezone()

    data = {
        "timestamp": now.isoformat(),
        "epoch": time.time(),
        "hostname": os.uname().nodename,
    }

    services = {}

    for unit in SERVICES:

        services[unit] = (
            systemd_state(unit)
        )

    data["services"] = services


    # HTTP
    web = http_get(
        "http://127.0.0.1:8094/"
    )

    queue = http_get(
        "http://127.0.0.1:8095/status",
        expect_json=True,
    )

    likes = http_get(
        "http://127.0.0.1:8096/api/list",
        expect_json=True,
    )

    # MR_HEALTH_8097_V3
    stats8097 = http_get(
        "http://127.0.0.1:8097/"
    )

    # MR_HEALTH_8099_8100_V1
    viewer8099 = http_get(
        "http://127.0.0.1:8099/healthz",
        expect_json=True,
    )

    trajectory8100 = http_get(
        "http://127.0.0.1:8100/healthz",
        expect_json=True,
    )

    # MR_HEALTH_COMPACT_HISTORY_V2
    #
    # Pełna odpowiedź JSON jest potrzebna lokalnie
    # do analizy queue/likes, ale NIE zapisujemy jej
    # później do latest.json/history.jsonl.
    #
    # Dzięki temu historia pozostaje mała nawet
    # przy setkach detekcji w API 8096.
    def compact_http(result):
        return {
            k: v
            for k, v in result.items()
            if k != "json"
        }

    data["http"] = {
        "8094": compact_http(web),
        "8095": compact_http(queue),
        "8096": compact_http(likes),
        "8097": compact_http(stats8097),
        "8099": compact_http(viewer8099),
        "8100": compact_http(trajectory8100),
    }


    # SYSTEM
    load1, load5, load15 = (
        os.getloadavg()
    )

    temp = temperature()

    throttle = throttled()

    disk = shutil.disk_usage("/")

    zombies = zombie_processes()

    radar = radar_stats()

    kernel = recent_kernel_events()


    data["system"] = {
        "load1": round(load1, 3),
        "load5": round(load5, 3),
        "load15": round(load15, 3),
        "temperature_c": temp,

        "disk_total_gib":
            round(
                disk.total
                / 1024**3,
                2,
            ),

        "disk_used_gib":
            round(
                disk.used
                / 1024**3,
                2,
            ),

        "disk_free_gib":
            round(
                disk.free
                / 1024**3,
                2,
            ),

        "disk_used_pct":
            round(
                disk.used
                / disk.total
                * 100,
                1,
            ),

        "throttled": throttle,

        "zombie_count":
            len(zombies),

        "zombies":
            zombies[:20],
    }

    data["radar"] = radar

    data["kernel_recent"] = kernel


    # Wyciągamy najważniejsze dane
    # z API 8095.
    queue_json = (
        queue.get("json")
        if isinstance(
            queue.get("json"),
            dict,
        )
        else {}
    )

    data["score"] = {
        "total":
            queue_json.get("total"),

        "scored":
            queue_json.get("scored"),

        "remaining":
            queue_json.get("remaining"),

        "ready":
            queue_json.get("ready"),

        "state":
            queue_json.get("state"),

        "active":
            queue_json.get("active"),

        "systemd_state":
            queue_json.get(
                "systemd_state"
            ),

        "indexed_total":
            queue_json.get(
                "indexed_total"
            ),

        "count_source":
            queue_json.get(
                "count_source"
            ),
    }


    likes_json = (
        likes.get("json")
        if isinstance(
            likes.get("json"),
            dict,
        )
        else {}
    )

    items = likes_json.get(
        "items",
        []
    )

    if not isinstance(
        items,
        list,
    ):
        items = []

    data["likes"] = {
        "items": len(items),

        "liked":
            sum(
                1
                for x in items
                if isinstance(x, dict)
                and x.get("liked")
            ),
    }


    # ==================================
    # OCENA STANU
    # ==================================

    issues = []


    def issue(level, code, text):

        issues.append(
            {
                "level": level,
                "code": code,
                "text": text,
            }
        )


    # MeteorRadio
    meteor = services.get(
        "meteorradio.service",
        {},
    )

    if (
        meteor.get("ActiveState")
        != "active"
        or
        meteor.get("SubState")
        != "running"
    ):

        issue(
            "CRIT",
            "METEORRADIO_SERVICE",
            "meteorradio.service nie jest active/running",
        )


    # Web 8094
    websvc = services.get(
        "meteorradio-web.service",
        {},
    )

    if (
        websvc.get("ActiveState")
        != "active"
    ):

        issue(
            "CRIT",
            "WEB_SERVICE",
            "meteorradio-web.service nie jest active",
        )


    # 8094/8095/8096
    for port, result in (
        ("8094", web),
        ("8095", queue),
        ("8096", likes),
        ("8097", stats8097),
        ("8099", viewer8099),
        ("8100", trajectory8100),
    ):

        if not result.get("ok"):

            issue(
                "CRIT",
                f"HTTP_{port}",
                f"port {port} nie odpowiada poprawnie",
            )


    # Timery
    for unit in (
        "meteorradio-score-new.timer",
        "meteorradio-retention.timer",
    ):

        s = services.get(
            unit,
            {},
        )

        if (
            s.get("ActiveState")
            != "active"
        ):

            issue(
                "CRIT",
                "TIMER",
                f"{unit} nie jest active",
            )


    # queue/likes service
    for unit in (
        "meteorradio-likes.service",
        "meteorradio-queue-status.service",
        "meteorradio-stats.service",
        "meteorradio-3d.service",
        "meteorradio-trajectory.service",
    ):

        s = services.get(
            unit,
            {},
        )

        if (
            s.get("ActiveState")
            != "active"
        ):

            issue(
                "CRIT",
                "SERVICE",
                f"{unit} nie jest active",
            )


    # Pre-render może być wyłączony
    # podczas scoringu — to normalne.
    pre = services.get(
        "meteorradio-prerender.service",
        {},
    )

    score_service = services.get(
        "meteorradio-score-new.service",
        {},
    )

    if (
        pre.get("ActiveState")
        != "active"
        and
        score_service.get("ActiveState")
        not in (
            "active",
            "activating",
        )
    ):

        issue(
            "WARN",
            "PRERENDER",
            "pre-render nieaktywny poza aktywnym scoringiem",
        )


    # temperatura
    if temp is not None:

        if temp >= 75:

            issue(
                "CRIT",
                "TEMP",
                f"temperatura {temp:.1f} C >= 75 C",
            )

        elif temp >= 70:

            issue(
                "WARN",
                "TEMP",
                f"temperatura {temp:.1f} C >= 70 C",
            )


    # MR_HEALTH_LOAD_SUSTAINED_V2
    #
    # load1 potrafi chwilowo skoczyć przy scoringu,
    # pre-renderze lub innych krótkich zadaniach.
    #
    # CRIT wymaga więc jednocześnie:
    #   load1 >= 4.5
    #   load5 >= 3.5
    #
    # Sam chwilowy skok load1 daje WARN.
    if (
        load1 >= 4.5
        and
        load5 >= 3.5
    ):

        issue(
            "CRIT",
            "LOAD_SUSTAINED",
            (
                f"utrzymujące się obciążenie "
                f"load1={load1:.2f} "
                f"load5={load5:.2f}"
            ),
        )

    elif (
        load1 >= 3.5
        or
        load5 >= 3.0
    ):

        issue(
            "WARN",
            "LOAD_TRANSIENT",
            (
                f"podwyższone obciążenie "
                f"load1={load1:.2f} "
                f"load5={load5:.2f}"
            ),
        )


    # miejsce
    free_gib = (
        disk.free
        / 1024**3
    )

    if free_gib < 2:

        issue(
            "CRIT",
            "DISK",
            f"wolne tylko {free_gib:.2f} GiB",
        )

    elif free_gib < 5:

        issue(
            "WARN",
            "DISK",
            f"wolne {free_gib:.2f} GiB",
        )


    # throttling — liczą się tylko
    # AKTYWNE bity 0..3.
    active_throttle = (
        throttle.get(
            "active_bits"
        )
    )

    if active_throttle:

        issue(
            "CRIT",
            "THROTTLE_ACTIVE",
            "aktywny throttling/undervoltage/soft-temp",
        )


    # zombie
    zc = len(zombies)

    if zc >= 10:

        issue(
            "CRIT",
            "ZOMBIE",
            f"{zc} procesów zombie",
        )

    elif zc > 3:

        issue(
            "WARN",
            "ZOMBIE",
            f"{zc} procesów zombie",
        )


    # kernel
    if (
        kernel.get("available")
        and
        kernel.get("count", 0) > 0
    ):

        issue(
            "WARN",
            "KERNEL",
            f"{kernel.get('count')} istotnych komunikatów kernela z ostatnich 35 min",
        )


    # Jeśli są dane oczekujące,
    # ale timer scoringu nie działa.
    remaining = data["score"].get(
        "remaining"
    )

    score_timer = services.get(
        "meteorradio-score-new.timer",
        {},
    )

    if (
        isinstance(
            remaining,
            int,
        )
        and remaining > 0
        and score_timer.get(
            "ActiveState"
        ) != "active"
    ):

        issue(
            "CRIT",
            "SCORE_QUEUE_NO_TIMER",
            f"remaining={remaining}, ale timer scoringu nieaktywny",
        )


    overall = "OK"

    for x in issues:

        if (
            severity_rank(
                x["level"]
            )
            >
            severity_rank(overall)
        ):
            overall = x["level"]


    data["status"] = overall
    data["issues"] = issues


    # ==================================
    # ZAPIS
    # ==================================

    tmp_json = LATEST_JSON.with_suffix(
        ".json.tmp"
    )

    tmp_json.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        tmp_json,
        LATEST_JSON,
    )


    with HISTORY.open(
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            json.dumps(
                data,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
            + "\n"
        )


    # Ograniczenie historii.
    try:

        lines = HISTORY.read_text(
            encoding="utf-8"
        ).splitlines()

        if len(lines) > MAX_HISTORY_LINES:

            HISTORY.write_text(
                "\n".join(
                    lines[
                        -MAX_HISTORY_LINES:
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

    except Exception:
        pass


    pid = meteor.get(
        "MainPID",
        "0",
    )


    txt = []

    txt.append(
        "MeteorRadio Health Check"
    )

    txt.append(
        f"TIME={data['timestamp']}"
    )

    txt.append(
        f"STATUS={overall}"
    )

    txt.append(
        f"METEOR_PID={pid}"
    )

    txt.append(
        "TEMP_C="
        + (
            f"{temp:.1f}"
            if temp is not None
            else "N/A"
        )
    )

    txt.append(
        f"LOAD={load1:.2f} "
        f"{load5:.2f} "
        f"{load15:.2f}"
    )

    txt.append(
        f"DISK_FREE_GIB="
        f"{free_gib:.2f}"
    )

    txt.append(
        f"SMP_COUNT="
        f"{radar['smp_count']}"
    )

    txt.append(
        f"RADAR_MIB="
        f"{radar['mib']}"
    )

    txt.append(
        f"SCORE_REMAINING="
        f"{data['score'].get('remaining')}"
    )

    txt.append(
        f"SCORE_STATE="
        f"{data['score'].get('state')}"
    )

    txt.append(
        f"SCORE_ACTIVE="
        f"{data['score'].get('active')}"
    )

    txt.append(
        f"LIKED="
        f"{data['likes']['liked']}"
    )

    txt.append(
        f"ZOMBIE_COUNT="
        f"{zc}"
    )

    txt.append(
        f"THROTTLED="
        f"{throttle.get('hex')}"
    )

    txt.append(
        f"THROTTLE_ACTIVE_BITS="
        f"{throttle.get('active_bits')}"
    )

    txt.append(
        f"KERNEL_EVENTS="
        f"{kernel.get('count', 0)}"
    )

    txt.append(
        f"HTTP8094="
        f"{web.get('http')}"
    )

    txt.append(
        f"HTTP8095="
        f"{queue.get('http')}"
    )

    txt.append(
        f"HTTP8096="
        f"{likes.get('http')}"
    )

    txt.append(
        f"HTTP8097="
        f"{stats8097.get('http')}"
    )


    if issues:

        txt.append(
            "ISSUES:"
        )

        for x in issues:

            txt.append(
                f"  [{x['level']}] "
                f"{x['code']}: "
                f"{x['text']}"
            )

    else:

        txt.append(
            "ISSUES=NONE"
        )


    LATEST_TXT.write_text(
        "\n".join(txt)
        + "\n",
        encoding="utf-8",
    )


    # Czytelny wpis również do journalctl.
    print(
        f"STATUS={overall} "
        f"temp={temp} "
        f"load1={load1:.2f} "
        f"free={free_gib:.2f}GiB "
        f"smp={radar['smp_count']} "
        f"remaining={data['score'].get('remaining')} "
        f"zombies={zc} "
        f"issues={len(issues)}"
    )

    for x in issues:

        print(
            f"{x['level']} "
            f"{x['code']} "
            f"{x['text']}"
        )


if __name__ == "__main__":
    main()
