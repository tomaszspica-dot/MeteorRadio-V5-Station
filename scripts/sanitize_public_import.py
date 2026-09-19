#!/usr/bin/env python3

from pathlib import Path
from urllib.parse import urlsplit
import sys


if len(sys.argv) != 2:
    raise SystemExit(
        "usage: sanitize_public_import.py REPO_ROOT"
    )


root = Path(sys.argv[1]).resolve()

app = root / "software/meteorradio-web/app.py"
likes = root / "software/meteorradio-web/likes_server.py"
stats = root / "software/meteorradio-stats/stats_server.py"


# Prywatne identyfikatory składamy z fragmentów,
# aby same nie występowały literalnie w publicznym repo.

old_host = "sat" + "nogspi"
old_fqdn = old_host + ".local"

old_ip = ".".join(
    [
        "192",
        "168",
        "1",
        "102",
    ]
)


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(
            f"ABORT: missing file: {path}"
        )

    return path.read_text(
        encoding="utf-8"
    )


def write(path: Path, text: str) -> None:
    path.write_text(
        text,
        encoding="utf-8"
    )


def replace_exact_once(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:

    count = text.count(old)

    if count != 1:
        raise SystemExit(
            f"ABORT: {label}: "
            f"expected 1 match, got {count}"
        )

    return text.replace(
        old,
        new,
        1,
    )


def nav(port: int) -> str:
    return (
        'href="#" '
        'onclick="location.href='
        'location.protocol+'
        "'//'"
        "+location.hostname+':"
        + str(port)
        + "/'; return false;\""
    )


# ============================================================
# 8094
# ============================================================

text = read(app)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8096/"',
    nav(8096),
    "8094 -> 8096 nav",
)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8097/"',
    nav(8097),
    "8094 -> 8097 nav",
)


# Dwa stare awaryjne endpointy IP do 8096.
# Usuwamy całe linie, a nie fragment składni.

target_ip_8096 = (
    f'"http://{old_ip}:8096"'
)

lines = text.splitlines(
    keepends=True
)

removed = sum(
    1
    for line in lines
    if target_ip_8096 in line
)

if removed != 2:
    raise SystemExit(
        "ABORT: static app.py 8096 "
        f"fallback count={removed}"
    )

text = "".join(
    line
    for line in lines
    if target_ip_8096 not in line
)

write(
    app,
    text,
)


# ============================================================
# 8096 — NAV
# ============================================================

text = read(likes)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8094/"',
    nav(8094),
    "8096 -> 8094 nav",
)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8097/"',
    nav(8097),
    "8096 -> 8097 nav",
)


# ============================================================
# 8096 — CORS
# ============================================================

old_cors = f'''        _origin=self.headers.get(
            "Origin"
        )

        if _origin in (
            "http://{old_fqdn}:8094",
            "http://{old_host}:8094",
            "http://{old_ip}:8094",
        ):'''


new_cors = '''        _origin=self.headers.get(
            "Origin"
        )

        _origin_ok=False

        if _origin:

            try:

                _origin_url=urlsplit(
                    _origin
                )

                _request_url=urlsplit(
                    "//"
                    +
                    self.headers.get(
                        "Host",
                        ""
                    )
                )

                _origin_port=(
                    _origin_url.port
                    if _origin_url.port is not None
                    else (
                        443
                        if _origin_url.scheme == "https"
                        else 80
                    )
                )

                _origin_host=(
                    _origin_url.hostname
                    or
                    ""
                ).lower()

                _request_host=(
                    _request_url.hostname
                    or
                    ""
                ).lower()

                _origin_ok=(
                    _origin_url.scheme
                    in (
                        "http",
                        "https",
                    )
                    and
                    _origin_port == 8094
                    and
                    _origin_host == _request_host
                )

            except Exception:

                _origin_ok=False

        if _origin_ok:'''


count = text.count(
    old_cors
)

if count != 1:
    raise SystemExit(
        "ABORT: likes CORS block count="
        + str(count)
    )

text = text.replace(
    old_cors,
    new_cors,
    1,
)


# Potrzebny import dla urlsplit.

import_anchor = "import "

if "from urllib.parse import urlsplit" not in text:

    first_import_end = text.find(
        "\n",
        text.find(import_anchor)
    )

    if first_import_end < 0:
        raise SystemExit(
            "ABORT: cannot insert urlsplit import"
        )

    text = (
        text[:first_import_end + 1]
        +
        "from urllib.parse import urlsplit\n"
        +
        text[first_import_end + 1:]
    )


write(
    likes,
    text,
)


# ============================================================
# 8097
# ============================================================

text = read(stats)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8094/"',
    nav(8094),
    "8097 -> 8094 nav",
)

text = replace_exact_once(
    text,
    f'href="http://{old_fqdn}:8096/"',
    nav(8096),
    "8097 -> 8096 nav",
)

write(
    stats,
    text,
)


# ============================================================
# FINAL PRIVACY GATE
# ============================================================

for path in (
    app,
    likes,
    stats,
):

    data = read(path)

    for needle in (
        old_host,
        old_fqdn,
        old_ip,
    ):

        if needle in data:
            raise SystemExit(
                "ABORT: station-specific "
                f"identifier remains in {path}: "
                f"{needle}"
            )


print(
    "PUBLIC_SANITIZE=PASS"
)
