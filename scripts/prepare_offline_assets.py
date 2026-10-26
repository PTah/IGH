#!/usr/bin/env python3
"""Скачать Leaflet + тайлы ArcGIS вдоль маршрута героя (не весь континент).

  python scripts/prepare_offline_assets.py --profile medium
  python scripts/prepare_offline_assets.py --profile full

Кэш: map/tiles-cache/<profile>/
Подробные зумы — только буфер вокруг линии маршрута и хабов.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "map" / "vendor"
CACHE_ROOT = ROOT / "map" / "tiles-cache"
LEAFLET_VER = "1.9.4"
UA = "IGH-offline-prep/0.5.0 (memorial map; route-buffered tile cache)"

TILE_TMPL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
)
MIN_TILE_BYTES = 1500

# medium: обзор; full: улицы вдоль пути
PROFILES = {
    "medium": {
        "world_max_z": 4,
        # (z, tile_radius) — квадрат (2r+1)² вокруг точки маршрута
        "route_zooms": [(5, 2), (6, 2)],
        "hub_zooms": [],
        "max_native_zoom": 6,
        "sample_step_m": 4000.0,
    },
    "full": {
        "world_max_z": 4,
        # вдоль всего пути — до z10; улицы (z11–14) — только у хабов
        "route_zooms": [
            (5, 2),
            (6, 2),
            (7, 2),
            (8, 2),
            (9, 1),
            (10, 1),
        ],
        "hub_zooms": [
            (11, 2),
            (12, 2),
            (13, 1),
            (14, 1),
        ],
        "max_native_zoom": 14,
        "sample_step_m": 2500.0,
    },
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def write_leaflet() -> None:
    base = VENDOR / "leaflet"
    base.mkdir(parents=True, exist_ok=True)
    for name in ("leaflet.js", "leaflet.css"):
        path = base / name
        if path.exists() and path.stat().st_size > 1000:
            print("leaflet skip", name, flush=True)
            continue
        url = f"https://unpkg.com/leaflet@{LEAFLET_VER}/dist/{name}"
        path.write_bytes(fetch(url))
        print("leaflet", name, flush=True)
    img = base / "images"
    img.mkdir(exist_ok=True)
    for name in ("marker-icon.png", "marker-icon-2x.png", "marker-shadow.png"):
        path = img / name
        if path.exists():
            continue
        url = f"https://unpkg.com/leaflet@{LEAFLET_VER}/dist/images/{name}"
        try:
            path.write_bytes(fetch(url))
            print("leaflet image", name, flush=True)
        except Exception as exc:
            print("skip image", name, exc, flush=True)


def write_world() -> None:
    path = VENDOR / "world.geojson"
    if path.exists() and path.stat().st_size > 1000:
        print("world skip", flush=True)
        return
    url = (
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "master/geojson/ne_110m_land.geojson"
    )
    data = json.loads(fetch(url).decode("utf-8"))
    feats = [
        {
            "type": "Feature",
            "properties": {"name": "land"},
            "geometry": f.get("geometry"),
        }
        for f in data.get("features", [])
    ]
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": feats},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"world.geojson features={len(feats)}", flush=True)


def latlon_to_tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def load_map_data() -> dict:
    data_js = ROOT / "map" / "data.js"
    if not data_js.exists():
        return {}
    text = data_js.read_text(encoding="utf-8")
    m = re.search(r"window\.MAP_DATA = (\{.*\});?\s*$", text, re.S)
    if not m:
        return {}
    return json.loads(m.group(1))


def load_hubs(data: dict) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for f in data.get("hubs", {}).get("features", []):
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            out.append((float(coords[1]), float(coords[0])))
    return out


def load_route_vertices(data: dict) -> list[tuple[float, float]]:
    """(lat, lon) вдоль всех сегментов маршрута."""
    out: list[tuple[float, float]] = []
    for f in data.get("route", {}).get("features", []):
        g = f.get("geometry") or {}
        coords = g.get("coordinates") or []
        typ = g.get("type")
        lines: list = []
        if typ == "LineString":
            lines = [coords]
        elif typ == "MultiLineString":
            lines = coords
        for line in lines:
            for c in line:
                if len(c) >= 2:
                    out.append((float(c[1]), float(c[0])))
    return out


def sample_along_route(
    verts: list[tuple[float, float]], step_m: float
) -> list[tuple[float, float]]:
    if not verts:
        return []
    samples = [verts[0]]
    acc = 0.0
    prev = verts[0]
    for cur in verts[1:]:
        d = haversine_m(prev[0], prev[1], cur[0], cur[1])
        acc += d
        if acc >= step_m:
            samples.append(cur)
            acc = 0.0
        prev = cur
    if samples[-1] != verts[-1]:
        samples.append(verts[-1])
    return samples


def add_disk(
    jobs: set[tuple[int, int, int]], lat: float, lon: float, z: int, radius: int
) -> None:
    n = 2**z
    cx, cy = latlon_to_tile(lat, lon, z)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < n and 0 <= y < n:
                jobs.add((z, x, y))


def iter_tile_jobs(profile: str) -> list[tuple[int, int, int]]:
    cfg = PROFILES[profile]
    data = load_map_data()
    hubs = load_hubs(data)
    verts = load_route_vertices(data)
    samples = sample_along_route(verts, cfg["sample_step_m"])
    # хабы всегда в выборке
    samples.extend(hubs)
    print(
        f"route verts={len(verts)} samples={len(samples)} hubs={len(hubs)}",
        flush=True,
    )

    jobs: set[tuple[int, int, int]] = set()
    for z in range(0, cfg["world_max_z"] + 1):
        n = 2**z
        for x in range(n):
            for y in range(n):
                jobs.add((z, x, y))

    for z, radius in cfg["route_zooms"]:
        for lat, lon in samples:
            add_disk(jobs, lat, lon, z, radius)
    for z, radius in cfg.get("hub_zooms") or []:
        for lat, lon in hubs:
            add_disk(jobs, lat, lon, z, radius)

    return sorted(jobs)


def _download_one(dest_root: Path, job: tuple[int, int, int], force: bool) -> str:
    z, x, y = job
    dest = dest_root / str(z) / str(x) / f"{y}.jpg"
    if dest.exists() and dest.stat().st_size >= MIN_TILE_BYTES and not force:
        if dest.read_bytes()[:3] == b"\xff\xd8\xff":
            return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = TILE_TMPL.format(z=z, x=x, y=y)
    try:
        data = fetch(url)
        if len(data) < MIN_TILE_BYTES or data[:3] != b"\xff\xd8\xff":
            return "fail"
        dest.write_bytes(data)
        return "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return "fail"


def prune_extra(dest_root: Path, jobs: list[tuple[int, int, int]]) -> int:
    needed = set(jobs)
    removed = 0
    for path in dest_root.rglob("*.jpg"):
        try:
            y = int(path.stem)
            x = int(path.parent.name)
            z = int(path.parent.parent.name)
        except ValueError:
            continue
        if (z, x, y) not in needed:
            path.unlink(missing_ok=True)
            removed += 1
    # убрать пустые каталоги
    for d in sorted(dest_root.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


def write_tiles(profile: str, force: bool = False, prune: bool = True) -> Path:
    cfg = PROFILES[profile]
    dest_root = CACHE_ROOT / profile
    dest_root.mkdir(parents=True, exist_ok=True)
    jobs = iter_tile_jobs(profile)
    print(f"profile={profile} jobs={len(jobs)} -> {dest_root}", flush=True)
    ok = skip = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {
            pool.submit(_download_one, dest_root, job, force): job for job in jobs
        }
        for i, fut in enumerate(as_completed(futs), 1):
            status = fut.result()
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                fail += 1
            if i % 200 == 0 or i == len(jobs):
                print(
                    f"tiles {i}/{len(jobs)} ok={ok} skip={skip} fail={fail} "
                    f"{time.time() - t0:.0f}s",
                    flush=True,
                )
    removed = prune_extra(dest_root, jobs) if prune else 0
    if removed:
        print(f"pruned extra tiles: {removed}", flush=True)
    manifest = {
        "profile": profile,
        "template": "tiles/{z}/{x}/{y}.jpg",
        "min_zoom": 0,
        "max_native_zoom": cfg["max_native_zoom"],
        "attribution": "Esri / OpenStreetMap contributors (offline cache)",
        "tile_count": ok + skip,
        "source": "ArcGIS World_Street_Map",
        "strategy": "route-buffer",
    }
    (dest_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("tiles done", manifest, flush=True)
    return dest_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--profile",
        choices=["medium", "full", "all"],
        default="all",
        help="medium = простые; full = подробные вдоль маршрута",
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-prune", action="store_true")
    ap.add_argument(
        "--count-only",
        action="store_true",
        help="только посчитать тайлы, без скачивания",
    )
    args = ap.parse_args()
    VENDOR.mkdir(parents=True, exist_ok=True)
    if args.count_only:
        profiles = ["medium", "full"] if args.profile == "all" else [args.profile]
        for p in profiles:
            jobs = iter_tile_jobs(p)
            print(p, "jobs", len(jobs), flush=True)
        return 0
    write_leaflet()
    write_world()
    profiles = ["medium", "full"] if args.profile == "all" else [args.profile]
    for p in profiles:
        write_tiles(p, force=args.force, prune=not args.no_prune)
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
