#!/usr/bin/env python3
"""Сборка трёх релизов: online / offline-medium / offline-full."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DIST = ROOT / "dist"
MAP_SRC = ROOT / "map"
LAUNCHER = ROOT / "launchers" / "igh_launcher.py"
CACHE = MAP_SRC / "tiles-cache"

VARIANTS = {
    "online": {
        "suffix": "online",
        "title": "онлайн-карты (OSM)",
        "mode": "online",
        "tiles_profile": None,
        "max_native_zoom": 18,
    },
    "offline-medium": {
        "suffix": "offline-medium",
        "title": "офлайн, простые карты (до z6 вдоль маршрута)",
        "mode": "offline",
        "tiles_profile": "medium",
        "max_native_zoom": 6,
    },
    "offline-full": {
        "suffix": "offline-full",
        "title": "офлайн, подробные карты только рядом с маршрутом (до z14)",
        "mode": "offline",
        "tiles_profile": "full",
        "max_native_zoom": 14,
    },
}


def ensure_data() -> None:
    if not (MAP_SRC / "data.js").exists():
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "build_map_data.py")]
        )


def ensure_vendor_and_tiles(profiles_needed: set[str]) -> None:
    leaflet = MAP_SRC / "vendor" / "leaflet" / "leaflet.js"
    if not leaflet.exists():
        subprocess.check_call(
            [
                sys.executable,
                str(ROOT / "scripts" / "prepare_offline_assets.py"),
                "--profile",
                "medium",
            ]
        )
    for prof in sorted(profiles_needed):
        mani = CACHE / prof / "manifest.json"
        if not mani.exists():
            print(f"tiles-cache/{prof} missing — downloading…")
            subprocess.check_call(
                [
                    sys.executable,
                    "-u",
                    str(ROOT / "scripts" / "prepare_offline_assets.py"),
                    "--profile",
                    prof,
                ]
            )


def write_map_config(dest_map: Path, variant: dict) -> None:
    cfg = {
        "mode": variant["mode"],
        "maxNativeZoom": variant["max_native_zoom"],
        "tileTemplate": "tiles/{z}/{x}/{y}.jpg",
        "variant": variant["suffix"],
        "version": VERSION,
    }
    (dest_map / "map-config.js").write_text(
        "window.IGH_MAP_CONFIG = "
        + json.dumps(cfg, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    # заголовок вкладки (дубль с app.js; VERSION подставляется при сборке)
    index = dest_map / "index.html"
    if index.exists():
        title = f"Я! Еду! Домой! - карта маршрута - версия {VERSION}"
        html = re.sub(
            r"<title>.*?</title>",
            f"<title>{title}</title>",
            index.read_text(encoding="utf-8"),
            count=1,
            flags=re.S,
        )
        index.write_text(html, encoding="utf-8")


def copy_map_base(dest: Path, include_tiles_from: Path | None) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns(
        "geo", "*.md", "tiles", "tiles-cache", "map-config.js"
    )
    shutil.copytree(MAP_SRC, dest, ignore=ignore)
    if include_tiles_from is not None:
        tiles_dest = dest / "tiles"
        if tiles_dest.exists():
            shutil.rmtree(tiles_dest)
        shutil.copytree(include_tiles_from, tiles_dest)


def write_readme(dest: Path, variant: dict) -> None:
    mode = variant["mode"]
    if mode == "online":
        net = (
            "Нужен интернет: подложка OpenStreetMap онлайн.\n"
            "Маршрут и данные — локальные."
        )
    else:
        net = (
            "Полностью офлайн: тайлы карты внутри пакета.\n"
            "При запуске ничего не скачивается из интернета."
        )
    text = f"""IGH — «Я! Еду! Домой!» — {variant['title']} (v{VERSION})
========================================

{net}

Windows: IGH.exe
  Распаковать zip целиком (нужна папка map/ рядом с exe).
  Лог — igh.log; остановка: IGH.exe --quit
macOS:   IGH.command  или  python3 igh_launcher.py

Варианты релизов
----------------
- online          — OSM в сети, без тайлов в архиве
- offline-medium  — офлайн обзор (зумы до ~6)
- offline-full    — офлайн + улицы у остановок (зумы до ~14)

© мемориальная карта маршрута трилогии Андрея Круза.
"""
    (dest / "README.txt").write_text(text, encoding="utf-8")


def write_macos_command(dest: Path) -> None:
    body = """#!/bin/bash
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  osascript -e 'display alert "Нужен Python 3" message "Установите Python с python.org"'
  exit 1
fi
exec "$PY" igh_launcher.py
"""
    path = dest / "IGH.command"
    path.write_bytes(body.replace("\r\n", "\n").encode("utf-8"))
    try:
        path.chmod(0o755)
    except OSError:
        pass


def build_exe(rel: Path, map_dir: Path, exe_name: str = "IGH") -> Path | None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not installed — skip .exe")
        return None

    work = DIST / f"_pyi_{rel.name}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    map_for_bundle = work / "map"
    if map_for_bundle.exists():
        shutil.rmtree(map_for_bundle)
    shutil.copytree(map_dir, map_for_bundle)
    launcher_copy = work / "igh_launcher.py"
    shutil.copy2(LAUNCHER, launcher_copy)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        exe_name,
        "--distpath",
        str(rel),
        "--workpath",
        str(work / "build"),
        "--specpath",
        str(work),
        f"--add-data={map_for_bundle}{sep}map",
        "--noconsole",
        str(launcher_copy),
    ]
    print("PyInstaller:", exe_name, flush=True)
    subprocess.check_call(cmd)
    exe = rel / (f"{exe_name}.exe" if os.name == "nt" else exe_name)
    return exe if exe.exists() else None


def zip_release(rel: Path, zip_name: str) -> Path:
    zip_path = DIST / zip_name
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in rel.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(rel.parent).as_posix())
    print("zip:", zip_path, zip_path.stat().st_size, flush=True)
    return zip_path


def build_one(key: str) -> Path:
    variant = VARIANTS[key]
    rel_name = f"IGH-{VERSION}-{variant['suffix']}"
    rel = DIST / rel_name
    if rel.exists():
        shutil.rmtree(rel)
    rel.mkdir(parents=True)

    tiles_src = None
    if variant["tiles_profile"]:
        tiles_src = CACHE / variant["tiles_profile"]
        if not (tiles_src / "manifest.json").exists():
            raise SystemExit(f"missing tile cache: {tiles_src}")

    map_dest = rel / "map"
    copy_map_base(map_dest, tiles_src)
    write_map_config(map_dest, variant)
    shutil.copy2(LAUNCHER, rel / "igh_launcher.py")
    write_macos_command(rel)
    write_readme(rel, variant)

    exe = build_exe(rel, map_dest)
    if exe:
        print("exe:", exe, flush=True)

    return zip_release(rel, f"{rel_name}.zip")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--variant",
        choices=["online", "offline-medium", "offline-full", "all"],
        default="all",
    )
    args = ap.parse_args()
    ensure_data()
    keys = list(VARIANTS) if args.variant == "all" else [args.variant]
    needed = {
        VARIANTS[k]["tiles_profile"]
        for k in keys
        if VARIANTS[k]["tiles_profile"]
    }
    ensure_vendor_and_tiles(needed)
    DIST.mkdir(exist_ok=True)
    zips = []
    for k in keys:
        print("=== building", k, "===", flush=True)
        zips.append(build_one(k))
    print("OK artifacts:")
    for z in zips:
        print(" ", z)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
