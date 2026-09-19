#!/usr/bin/env python3

import json
import os
import time
from pathlib import Path


SOURCE = Path(
    "/dev/shm/meteorradio-live/"
    "spectrum-fast.json"
)

DEST = Path(
    "/dev/shm/meteorradio-live/"
    "history-v5.json"
)

PERIOD = 0.60
MAX_AGE = 300.0
MAX_ROWS = 520


def load_old():

    try:

        d = json.loads(
            DEST.read_text(
                encoding="utf-8"
            )
        )

        rows = d.get(
            "rows",
            []
        )

        if isinstance(
            rows,
            list
        ):
            return rows

    except Exception:
        pass

    return []


def atomic_write(
    rows
):

    DEST.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "ok": True,
        "version": 5,
        "history_seconds": 300,
        "period_s": PERIOD,
        "rows": rows,
        "generated_epoch": time.time(),
    }

    tmp = DEST.with_suffix(
        ".tmp"
    )

    tmp.write_text(
        json.dumps(
            payload,
            separators=(
                ",",
                ":",
            ),
        ),
        encoding="utf-8",
    )

    os.replace(
        tmp,
        DEST,
    )


rows = load_old()

last_saved = 0.0
last_timestamp = None


while True:

    try:

        now = time.time()

        rows = [
            x
            for x in rows
            if (
                isinstance(
                    x,
                    dict
                )
                and
                now
                - float(
                    x.get(
                        "epoch",
                        0,
                    )
                )
                <= MAX_AGE
            )
        ][-MAX_ROWS:]


        if SOURCE.exists():

            d = json.loads(
                SOURCE.read_text(
                    encoding="utf-8"
                )
            )

            timestamp = d.get(
                "timestamp"
            )

            values = d.get(
                "power_db"
            )


            if (
                timestamp
                and
                isinstance(
                    values,
                    list
                )
                and
                values
                and
                timestamp
                != last_timestamp
                and
                now
                - last_saved
                >= PERIOD * 0.95
            ):

                cleaned = []

                for value in values:

                    try:
                        cleaned.append(
                            round(
                                float(
                                    value
                                ),
                                2,
                            )
                        )

                    except Exception:
                        cleaned.append(
                            0.0
                        )


                rows.append(
                    {
                        "epoch": now,
                        "timestamp":
                            timestamp,
                        "power_db":
                            cleaned,
                    }
                )

                rows = rows[
                    -MAX_ROWS:
                ]

                atomic_write(
                    rows
                )

                last_timestamp = (
                    timestamp
                )

                last_saved = now


        elif rows:

            atomic_write(
                rows
            )


    except Exception:
        pass


    time.sleep(
        0.08
    )
