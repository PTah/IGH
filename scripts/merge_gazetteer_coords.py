#!/usr/bin/env python3
"""Дополнить coords_seed из spine/gazetteer по совпадению name_map / name_book (осторожно)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from json_atomic import write_json  # noqa: E402
SEED = ROOT / "data/extracted/coords_seed.json"
GAZ = ROOT / "data/spine/gazetteer.json"
BOOKS = [
    ROOT / "data/extracted/book01_curated.json",
    ROOT / "data/extracted/book02_curated.json",
    ROOT / "data/extracted/book03_curated.json",
]


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'\.,;:()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    gaz = json.loads(GAZ.read_text(encoding="utf-8")).get("places", [])
    gaz_idx = {}
    for g in gaz:
        if g.get("lat") is None or g.get("lon") is None:
            continue
        for key in (g.get("name"), g.get("real")):
            if key:
                gaz_idx[norm(key)] = g

    places = []
    for bp in BOOKS:
        places.extend(json.loads(bp.read_text(encoding="utf-8")).get("places", []))

    added = []
    for p in places:
        pid = p["id"]
        if pid in seed and not str(pid).startswith("_"):
            continue
        if pid.startswith("_"):
            continue
        # уже есть
        if pid in seed:
            continue
        for key in (p.get("name_map"), p.get("name_book")):
            g = gaz_idx.get(norm(key or ""))
            if g:
                seed[pid] = [float(g["lat"]), float(g["lon"])]
                added.append((pid, key, g.get("name")))
                break

    # также: если place есть в seed — ничего; доклад по близким именам без записи
    suggestions = []
    for p in places:
        pid = p["id"]
        if pid not in seed:
            continue
        for key in (p.get("name_map"), p.get("name_book")):
            g = gaz_idx.get(norm(key or ""))
            if g:
                slat, slon = seed[pid]
                if abs(slat - g["lat"]) > 0.15 or abs(slon - g["lon"]) > 0.15:
                    suggestions.append(
                        {
                            "id": pid,
                            "seed": [slat, slon],
                            "gaz": [g["lat"], g["lon"]],
                            "gaz_name": g.get("name"),
                        }
                    )
                break

    write_json(SEED, seed)
    report = ROOT / "data/spine/gazetteer_merge_report.json"
    write_json(report, {"added": added, "divergences": suggestions[:40]})
    print(f"added={len(added)} divergences_noted={len(suggestions)} report={report}")


if __name__ == "__main__":
    main()
