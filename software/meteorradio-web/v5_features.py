#!/usr/bin/env python3

import json
from pathlib import Path


HISTORY = Path(
    "/dev/shm/meteorradio-live/"
    "history-v5.json"
)


def history_data():

    if not HISTORY.exists():

        return {
            "ok": True,
            "version": 5,
            "history_seconds": 300,
            "period_s": 0.6,
            "rows": [],
        }


    try:

        d = json.loads(
            HISTORY.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            d,
            dict
        ):
            raise ValueError(
                "invalid history"
            )

        d["ok"] = True

        return d


    except Exception as e:

        return {
            "ok": False,
            "error": str(e),
            "rows": [],
        }
