#!/usr/bin/env python3

import json
import re
import subprocess
import time

from pathlib import Path
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

PORT = 8095

RADAR = Path(
    "/home/pi/radar_data"
)

INDEX = Path(
    "/home/pi/meteorradio-web/"
    "cache/v562_score_index.json"
)

SERVICE = (
    "meteorradio-score-new.service"
)

WORKER_PATTERN = (
    "/home/pi/meteorradio-web/"
    "score_new_detections.py"
)

MIN_AGE = 30.0

_cache_time = 0.0
_cache_data = None


def systemd_state():

    try:

        p = subprocess.run(
            [
                "systemctl",
                "show",
                SERVICE,
                "-p",
                "ActiveState",
                "--value",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )

        return p.stdout.strip()

    except Exception:
        return ""


def worker_process():

    try:

        p = subprocess.run(
            [
                "pgrep",
                "-f",
                WORKER_PATTERN,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )

        return p.returncode == 0

    except Exception:
        return False


def service_active():

    state = systemd_state()

    if state in (
        "active",
        "activating",
        "reloading",
    ):
        return True

    return worker_process()


def journal():

    try:

        p = subprocess.run(
            [
                "journalctl",
                "-u",
                SERVICE,
                "-n",
                "1200",
                "--no-pager",
                "-o",
                "cat",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )

        return p.stdout.splitlines()

    except Exception:
        return []


def read_score_names():

    data = json.loads(
        INDEX.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(data, dict):

        scores = data.get(
            "scores"
        )

        if isinstance(scores, dict):

            return (
                set(scores.keys()),
                "score-index:scores"
            )

        direct = {
            k
            for k in data.keys()
            if isinstance(k, str)
            and k.startswith("SMP_")
        }

        if direct:

            return (
                direct,
                "score-index:direct"
            )

    raise RuntimeError(
        "unknown score-index structure"
    )


def current_segment(lines):

    starts = [
        i
        for i, line in enumerate(lines)
        if re.search(
            r"\bSTART\s*$",
            line
        )
    ]

    if not starts:
        return []

    return lines[
        starts[-1]:
    ]


def snapshot():

    global _cache_time
    global _cache_data

    now_mono = time.monotonic()

    if (
        _cache_data is not None
        and
        now_mono - _cache_time < 2.0
    ):
        return _cache_data

    try:

        files = {
            p.name: p
            for p in RADAR.glob(
                "SMP_*.npz"
            )
        }

        score_names, source = (
            read_score_names()
        )

        present_names = set(
            files.keys()
        )

        scored_present = (
            present_names
            &
            score_names
        )

        missing = (
            present_names
            -
            score_names
        )

        now = time.time()

        ready = 0

        for name in missing:

            try:

                age = (
                    now
                    -
                    files[name].stat().st_mtime
                )

                if age >= MIN_AGE:
                    ready += 1

            except Exception:
                pass

        lines = journal()

        segment = current_segment(
            lines
        )

        active = service_active()
        sd_state = systemd_state()

        queue_at_start = None

        for line in segment:

            m = re.search(
                r"\bINDEX\s+(\d+)"
                r"\s+QUEUE\s+(\d+)",
                line
            )

            if m:

                queue_at_start = int(
                    m.group(2)
                )

                break

        done_cycle = sum(
            1
            for line in segment
            if re.search(
                r"\bDONE\s+SMP_",
                line
            )
        )

        pause_pos = -1
        resume_pos = -1

        for i, line in enumerate(
            segment
        ):

            if "PAUSE " in line:
                pause_pos = i

            if (
                "RESUME resources stable"
                in line
            ):
                resume_pos = i

        if active:

            if pause_pos > resume_pos:
                state = "paused"

            else:
                state = "running"

        else:
            state = "idle"

        data = {
            "ok": True,
            "total": len(present_names),
            "scored": len(scored_present),
            "remaining": len(missing),
            "ready": ready,
            "too_young": max(
                0,
                len(missing) - ready
            ),
            "indexed_total": len(
                score_names
            ),
            "queue_at_start": queue_at_start,
            "done_cycle": done_cycle,
            "state": state,
            "active": active,
            "systemd_state": sd_state,
            "count_source": source,
        }

    except Exception as exc:

        data = {
            "ok": False,
            "error": str(exc),
        }

    _cache_time = now_mono
    _cache_data = data

    return data


class Handler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        fmt,
        *args
    ):
        return

    def do_GET(self):

        path = self.path.split(
            "?",
            1
        )[0]

        if path not in (
            "/",
            "/status",
        ):

            self.send_response(404)
            self.end_headers()
            return

        raw = json.dumps(
            snapshot(),
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Content-Length",
            str(
                len(raw)
            )
        )

        self.end_headers()

        self.wfile.write(raw)


server = ThreadingHTTPServer(
    (
        "0.0.0.0",
        PORT
    ),
    Handler
)

print(
    "MeteorRadio queue status: "
    "http://0.0.0.0:8095/status",
    flush=True
)

server.serve_forever()
