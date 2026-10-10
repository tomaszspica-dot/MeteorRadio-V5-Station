#!/usr/bin/env python3
"""Upload an RMOB TXT/JPEG pair through the official RMOBclient utility.

RMOBclient is a separately distributed binary. This repository does not bundle it.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload RMOB TXT/JPEG using RMOBclient"
    )
    parser.add_argument(
        "--client",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--txt",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--jpg",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    return parser.parse_args()


def validate_pair(txt: Path, jpg: Path) -> None:
    if not txt.is_file():
        raise SystemExit(f"Missing TXT: {txt}")
    if not jpg.is_file():
        raise SystemExit(f"Missing JPG: {jpg}")

    if not txt.name.lower().endswith("rmob.txt"):
        raise SystemExit(
            f"Unexpected TXT filename: {txt.name}"
        )

    if jpg.suffix.lower() not in {".jpg", ".jpeg"}:
        raise SystemExit(
            f"Unexpected JPEG extension: {jpg.name}"
        )

    # "Observer_MMYYYYrmob.TXT" and "Observer_MMYYYY.jpg"
    # must describe the same RMOB observation set.
    txt_prefix = txt.name[:-8]
    jpg_prefix = jpg.stem

    if txt_prefix != jpg_prefix:
        raise SystemExit(
            "RMOB pair has different prefixes: "
            f"TXT={txt_prefix!r}, JPG={jpg_prefix!r}"
        )


def run_upload(
    client: Path,
    txt: Path,
    jpg: Path,
    *,
    dry_run: bool = False,
) -> None:
    validate_pair(txt, jpg)

    if dry_run:
        print("RMOB_UPLOAD_DRY_RUN=YES")
        print("CLIENT=", client)
        print("TXT=", txt)
        print("JPG=", jpg)
        return

    if not client.is_file():
        raise SystemExit(
            f"Missing RMOBclient: {client}"
        )

    command = [
        str(client),
        txt.name,
        jpg.name,
    ]

    print(
        "RMOB_UPLOAD_COMMAND=",
        " ".join(command),
    )

    completed = subprocess.run(
        command,
        cwd=txt.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = completed.stdout or ""
    print(
        output,
        end=""
        if output.endswith("\n")
        else "\n",
    )

    no_error_count = output.count(
        "QNetworkReply::NoError"
    )

    print(
        "RMOBCLIENT_RC=",
        completed.returncode,
    )
    print(
        "RMOBCLIENT_NOERROR_COUNT=",
        no_error_count,
    )

    if completed.returncode != 0:
        raise SystemExit(
            "RMOBclient finished with code "
            f"{completed.returncode}"
        )

    if no_error_count != 2:
        raise SystemExit(
            "RMOBclient did not confirm both transfers: "
            f"NoError={no_error_count}"
        )

    print("RMOB_UPLOAD=PASS")


def main() -> None:
    args = parse_args()

    run_upload(
        args.client,
        args.txt,
        args.jpg,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
