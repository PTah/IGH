#!/usr/bin/env python3
"""Импорт spine из I.Go.To.Home → data/spine/ (только чтение IGTH).

  set IGTH_ROOT=path/to/I.Go.To.Home
  python scripts/import_spine_from_igth.py
  # или: python scripts/import_spine_from_igth.py --igth path/to/I.Go.To.Home
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "spine"

KIND_MAP = {
    "decision": "leads_to",
    "companion": "joins",
    "injury": "delays",
    "weather": "weather",
    "route": "leads_to",
    "encounter": "enables",
}


def igth_chapter_to_id(book: int, chapter: int) -> str:
    # IGTH chapter 1..N → book0X-ch000..
    return f"book{book:02d}-ch{chapter - 1:03d}"


def clean(s: str | None) -> str:
    if not s:
        return ""
    return str(s).replace("\xa0", " ").strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Import spine from I.Go.To.Home")
    ap.add_argument(
        "--igth",
        type=Path,
        default=os.environ.get("IGTH_ROOT") or None,
        help="Path to I.Go.To.Home clone (or set IGTH_ROOT)",
    )
    args = ap.parse_args()
    if not args.igth:
        raise SystemExit("Укажите путь: --igth PATH или env IGTH_ROOT")
    igth = Path(args.igth)
    if not igth.exists():
        raise SystemExit(f"IGTH not found: {igth}")

    route = json.loads((igth / "data/route.json").read_text(encoding="utf-8"))
    events = json.loads((igth / "data/events.json").read_text(encoding="utf-8"))
    graph = json.loads((igth / "data/graph.json").read_text(encoding="utf-8"))
    gaz = json.loads((igth / "data/gazetteer.json").read_text(encoding="utf-8"))
    key_ev = json.loads((igth / "data/key_events.json").read_text(encoding="utf-8"))

    ev_by_seq = {e["seq"]: e for e in events if isinstance(e, dict)}

    chapters = []
    for r in route:
        book = int(r["book"])
        ch = int(r["chapter"])
        cid = igth_chapter_to_id(book, ch)
        ev = ev_by_seq.get(r.get("seq"), {})
        chapters.append(
            {
                "chapter_id": cid,
                "seq": r.get("seq"),
                "book": book,
                "book_id": f"book{book:02d}",
                "chapter_num": ch,
                "date": clean(r.get("date")),
                "day": r.get("day"),
                "month": r.get("month"),
                "weekday": clean(r.get("weekday")),
                "time": clean(r.get("time")),
                "location": clean(r.get("location")),
                "raw_title": clean(r.get("raw")),
                "pov": ev.get("pov") or (
                    "family_ru"
                    if re.search(r"Москва|Подмосков|Пирогов|Пламя|Нахабин|Снегир", clean(r.get("location")), re.I)
                    and book < 3
                    else "protagonist"
                ),
                "summary": clean(ev.get("summary")),
                "types": ev.get("types") or [],
                "type_labels": ev.get("type_labels") or [],
                "pivots": ev.get("pivots") or [],
                "importance": ev.get("importance"),
                "density": ev.get("density"),
            }
        )

    # Fix POV using known Kronstadt arrival: from book03-ch061 family can be protagonist in RU
    # Keep imported pov from events.json primarily (already set).

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chapters.json").write_text(
        json.dumps(
            {
                "_source": "I.Go.To.Home data/route.json + events.json",
                "_note": "Календарный скелет 164 глав. Сюжетные карточки — в data/extracted/*_curated.json",
                "chapters": chapters,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Gazetteer with coords only + all names for lookup
    gaz_out = []
    for g in gaz:
        if not isinstance(g, dict):
            continue
        item = {
            "name": clean(g.get("name")),
            "type": g.get("type"),
            "country": g.get("country"),
            "region": clean(g.get("region")),
            "real": clean(g.get("real")),
            "note": clean(g.get("note")),
            "books": g.get("books"),
            "lat": g.get("lat"),
            "lon": g.get("lon"),
        }
        gaz_out.append(item)
    (OUT / "gazetteer.json").write_text(
        json.dumps({"_source": "I.Go.To.Home data/gazetteer.json", "places": gaz_out}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    # Graph: keep nodes/edges with chapter_id mapping where possible
    nodes_out = []
    node_meta = {}
    for n in graph.get("nodes", []):
        nid = n.get("id")
        book = n.get("book")
        chapter = n.get("chapter")
        chapter_id = None
        if book and chapter:
            chapter_id = igth_chapter_to_id(int(book), int(chapter))
        node = {
            "id": nid,
            "label": clean(n.get("label")),
            "kind": n.get("kind"),
            "book": book,
            "chapter": chapter,
            "chapter_id": chapter_id,
            "seq": n.get("seq"),
            "date": clean(n.get("date")),
            "time": clean(n.get("time")),
            "location": clean(n.get("location")),
            "lat": n.get("lat"),
            "lon": n.get("lon"),
        }
        nodes_out.append(node)
        node_meta[nid] = node

    edges_out = []
    for e in graph.get("edges", []):
        fr, to = e.get("from"), e.get("to")
        edges_out.append(
            {
                "id": f"igth-{fr}-{to}",
                "from": fr,
                "to": to,
                "from_chapter_id": (node_meta.get(fr) or {}).get("chapter_id"),
                "to_chapter_id": (node_meta.get(to) or {}).get("chapter_id"),
                "kind": KIND_MAP.get(e.get("type"), "leads_to"),
                "igth_type": e.get("type"),
                "impact": e.get("impact"),
                "summary": clean(e.get("note")),
                "source": "igth_graph",
            }
        )

    (OUT / "graph_igth.json").write_text(
        json.dumps(
            {"_source": "I.Go.To.Home data/graph.json", "nodes": nodes_out, "edges": edges_out},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Key events — import as reference only; flag known bad locations
    keys = []
    for k in key_ev:
        title = clean(k.get("title"))
        warn = None
        loc = clean(k.get("location"))
        if "Сэм" in title and "Юма" in loc:
            warn = "IGTH error: Сэм не в Юме — Джастисбёрг (книга 2)"
        if "Тигр" in title and "Юма" in loc:
            warn = "IGTH error: Тигр найден в Викенбурге, не в Юме"
        keys.append(
            {
                "title": title,
                "kind": k.get("kind"),
                "desc": clean(k.get("desc")),
                "book": k.get("book"),
                "seq": k.get("seq"),
                "date": clean(k.get("date")),
                "time": clean(k.get("time")),
                "location": loc,
                "lat": k.get("lat"),
                "lon": k.get("lon"),
                "import_warning": warn,
                "use_in_map": warn is None,
            }
        )
    (OUT / "key_events_igth.json").write_text(
        json.dumps({"_source": "I.Go.To.Home data/key_events.json", "events": keys}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    # Optional Mapbox coords overlay
    mb = igth / "data/coords_mapbox.json"
    if mb.exists():
        (OUT / "coords_mapbox.json").write_text(mb.read_text(encoding="utf-8"), encoding="utf-8")

    with_coords = sum(1 for g in gaz_out if g.get("lat") is not None)
    print(
        f"Wrote {OUT}: chapters={len(chapters)} gazetteer={len(gaz_out)} "
        f"(coords={with_coords}) graph_nodes={len(nodes_out)} edges={len(edges_out)} keys={len(keys)}"
    )


if __name__ == "__main__":
    main()
