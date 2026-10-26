#!/usr/bin/env python3
"""Атомарная запись JSON (+ опциональный .bak)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path | str, data: object, *, backup: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            pass
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
