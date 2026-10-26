#!/usr/bin/env python3
"""Fill chapters[] in book03_curated.json from TOC + event map."""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from json_atomic import write_json  # noqa: E402
cur = json.loads(
    (root / "data/extracted/book03_curated.json").read_text(encoding="utf-8")
)
toc = json.loads(
    (root / "data/extracted/book03_toc.json").read_text(encoding="utf-8")
)

# map chapter -> place ids (best-effort from title keywords)
PLACE_RULES = [
    ("Пласентиа", ["p-placentia-bay"]),
    ("Северная Атлантика", ["p-n-atlantic"]),
    ("Андалусии", ["p-andalusia-coast"]),
    ("Пуэрто-Банус", ["p-puerto-banus"]),
    ("Марбельи", ["p-marbella"]),
    ("Фуэнхирола", ["p-fuengirola-fort"]),
    ("Сьерра-Невада", ["p-sierra-nevada-road"]),
    ("Кантабрико", ["p-cantabrico"]),
    ("Антверпен", ["p-antwerp"]),
    ("Кааг", ["p-kaag"]),
    ("Мюйден", ["p-muiden"]),
    ("Пламя", ["p-plamya"]),
    ("Дельфзийль", ["p-delfzijl"]),
    ("Мариетт", ["p-marietta", "p-gotland"]),
    ("Кронштадт, городская больница", ["p-kronstadt-hospital"]),
    ("Кронштадт", ["p-kronstadt"]),
    ("Санкт-Петербург", ["p-spb-msk-road"]),
    ("Ржев", ["p-rzhev"]),
    ("Нахабино", ["p-nakhabino"]),
    ("Снегири", ["p-snegiri"]),
    ("Гринвич", ["p-greenwich"]),
    ("Эпилог", ["p-nakhabino"]),
]

FAMILY_UNTIL = "book03-ch061"

events_by_ch: dict[str, list[str]] = {}
for e in cur["events"]:
    events_by_ch.setdefault(e["chapter_id"], []).append(e["id"])

chapters = []
for ch in toc["chapters"]:
    cid = ch["id"]
    title = ch["title"]
    place_ids = []
    for key, pids in PLACE_RULES:
        if key in title:
            place_ids = pids
            break
    if "Подмосковье" in title or (
        "Пламя" in title and cid < FAMILY_UNTIL
    ):
        pov = "family_ru"
    elif cid < FAMILY_UNTIL and ("Пламя" in title):
        pov = "family_ru"
    else:
        pov = "protagonist"
    # override: Plamya chapters before kronstadt
    if "Пламя" in title and cid < FAMILY_UNTIL:
        pov = "family_ru"

    digest = title
    if cid in events_by_ch:
        digest = title + " | events: " + ", ".join(events_by_ch[cid])

    chapters.append(
        {
            "id": cid,
            "pov": pov,
            "place_ids": place_ids,
            "digest": digest,
            "event_ids": events_by_ch.get(cid, []),
            "status": "done",
        }
    )

cur["chapters"] = chapters
write_json(root / "data/extracted/book03_curated.json", cur)
print("chapters", len(chapters), "with events", sum(1 for c in chapters if c["event_ids"]))
