#!/usr/bin/env python3
"""Read-only compare this IGH repo vs I.Go.To.Home (no writes to IGTH).

  set IGTH_ROOT=path/to/I.Go.To.Home
  python scripts/compare_igth.py
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", type=Path, default=ROOT, help="IGH repo root")
    ap.add_argument(
        "--igth",
        type=Path,
        default=os.environ.get("IGTH_ROOT") or None,
        help="I.Go.To.Home clone (or set IGTH_ROOT)",
    )
    args = ap.parse_args()
    if not args.igth:
        raise SystemExit("Укажите путь: --igth PATH или env IGTH_ROOT")
    A = Path(args.ours)
    B = Path(args.igth)
    if not B.exists():
        raise SystemExit(f"IGTH not found: {B}")

    # --- ours ---
    b1 = load(A / "data/extracted/book01_curated.json")
    b2 = load(A / "data/extracted/book02_curated.json")
    b3 = load(A / "data/extracted/book03_curated.json")
    ours_events = []
    ours_places = {}
    ours_edges = []
    for b in (b1, b2, b3):
        for p in b.get("places", []):
            ours_places[p["id"]] = p
        for e in b.get("events", []):
            ours_events.append({**e, "book_id": b["book_id"]})
        for edge in b.get("edges", []):
            ours_edges.append({**edge, "book_id": b["book_id"]})

    # --- theirs ---
    route = load(B / "data/route.json")
    events = load(B / "data/events.json")
    graph = load(B / "data/graph.json")
    key_ev = load(B / "data/key_events.json")
    gaz = load(B / "data/gazetteer.json")
    # curated copies (partial)
    tb1 = load(B / "data/curated/book01_curated.json")
    tb2 = load(B / "data/curated/book02_curated.json")
    has_b3_curated = (B / "data/curated/book03_curated.json").exists()

    # gazetteer shape
    if isinstance(gaz, dict) and "places" in gaz:
        gaz_places = gaz["places"]
    elif isinstance(gaz, list):
        gaz_places = gaz
    else:
        gaz_places = gaz.get("items") or gaz.get("entries") or list(gaz.values()) if isinstance(gaz, dict) else []

    # route chapters
    if isinstance(route, dict):
        route_chapters = route.get("chapters") or route.get("stops") or route.get("legs") or []
        if not route_chapters and "books" in route:
            route_chapters = []
            for book in route["books"]:
                route_chapters.extend(book.get("chapters") or [])
    else:
        route_chapters = route

    # events list
    if isinstance(events, dict):
        ev_list = events.get("events") or events.get("chapters") or []
        if not ev_list and "by_chapter" in events:
            ev_list = []
            for ch, items in events["by_chapter"].items():
                for it in items if isinstance(items, list) else [items]:
                    ev_list.append({**(it if isinstance(it, dict) else {"raw": it}), "chapter": ch})
    else:
        ev_list = events

    # graph
    nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
    g_edges = graph.get("edges", []) if isinstance(graph, dict) else []

    print("=== COUNTS ===")
    print(f"OURS places={len(ours_places)} events={len(ours_events)} edges={len(ours_edges)} books=3 curated")
    print(f"IGTH gazetteer≈{len(gaz_places)} route_entries={len(route_chapters)} events={len(ev_list)}")
    print(f"IGTH graph nodes={len(nodes)} edges={len(g_edges)} key_events={len(key_ev) if isinstance(key_ev, list) else len(key_ev.get('events', key_ev.get('items', [])))}")
    print(f"IGTH curated book01/02 yes, book03_curated={has_b3_curated}")
    print(f"IGTH curated b1 events={len(tb1.get('events',[]))} places={len(tb1.get('places',[]))} edges={len(tb1.get('edges',[]))}")
    print(f"IGTH curated b2 events={len(tb2.get('events',[]))} places={len(tb2.get('places',[]))} edges={len(tb2.get('edges',[]))}")

    # sample keys
    print("\n=== IGTH TOP-LEVEL KEYS ===")
    print("route.json:", list(route.keys()) if isinstance(route, dict) else type(route))
    print("events.json:", list(events.keys()) if isinstance(events, dict) else type(events))
    print("graph.json:", list(graph.keys()) if isinstance(graph, dict) else type(graph))
    print("gazetteer.json:", list(gaz.keys())[:20] if isinstance(gaz, dict) else type(gaz))
    print("key_events.json:", list(key_ev.keys()) if isinstance(key_ev, dict) else f"list[{len(key_ev)}]")

    # place name overlap
    ours_names = {(p.get("name_map") or p.get("name_book") or "").lower() for p in ours_places.values()}
    gaz_names = set()
    gaz_with_coords = 0
    for g in gaz_places if isinstance(gaz_places, list) else []:
        if not isinstance(g, dict):
            continue
        nm = (g.get("name") or g.get("name_map") or g.get("name_book") or g.get("title") or "").lower()
        if nm:
            gaz_names.add(nm)
        if g.get("lat") is not None or g.get("lon") is not None or g.get("coordinates"):
            gaz_with_coords += 1
    print("\n=== PLACES ===")
    print(f"gazetteer with coords≈{gaz_with_coords}")
    print(f"name overlap (rough)={len(ours_names & gaz_names)}")

    # POV / family
    ours_family = sum(1 for e in ours_events if e.get("pov") == "family_ru")
    print(f"\nOURS family_ru events={ours_family} protagonist={len(ours_events)-ours_family}")

    # IGTH events sample importance/types
    types = {}
    povs = {}
    with_quote = 0
    for e in ev_list[:5000] if isinstance(ev_list, list) else []:
        if not isinstance(e, dict):
            continue
        t = e.get("type") or e.get("kind") or "?"
        types[t] = types.get(t, 0) + 1
        pv = e.get("pov") or e.get("viewpoint") or "?"
        povs[pv] = povs.get(pv, 0) + 1
        if e.get("quote") or e.get("excerpt") or e.get("snippet"):
            with_quote += 1
    print("\n=== IGTH event types (top) ===")
    for k, v in sorted(types.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k}: {v}")
    print("POV:", povs, "with_quote≈", with_quote)

    # graph edge kinds
    kinds = {}
    for e in g_edges:
        k = e.get("kind") or e.get("type") or "?"
        kinds[k] = kinds.get(k, 0) + 1
    print("\n=== IGTH graph edge kinds ===", kinds)
    ours_kinds = {}
    for e in ours_edges:
        k = e.get("kind") or "?"
        ours_kinds[k] = ours_kinds.get(k, 0) + 1
    print("OURS edge kinds ===", ours_kinds)

    # map features
    print("\n=== MAP ===")
    for label, root in (("OURS", A), ("IGTH", B)):
        app = (root / "map/app.js").read_text(encoding="utf-8")
        print(
            label,
            "timeline=",
            "tl-range" in app or "timeline" in app.lower(),
            "companions=",
            "companion" in app.lower(),
            "causal=",
            "causal" in app.lower() or "graph" in app.lower(),
            "quote=",
            "quote" in app.lower(),
            "osrm/road=",
            "osrm" in app.lower() or "road" in app.lower(),
            "bytes_app=",
            len(app),
            "data_js=",
            (root / "map/data.js").stat().st_size if (root / "map/data.js").exists() else 0,
        )


if __name__ == "__main__":
    main()
