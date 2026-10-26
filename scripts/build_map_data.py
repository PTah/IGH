#!/usr/bin/env python3
"""Build Leaflet map: hubs (не россыпь), дни сюжета, маршрут по дорогам OSRM."""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "data" / "extracted"
SPINE = ROOT / "data" / "spine"
MAP_DIR = ROOT / "map"
OUT_JS = MAP_DIR / "data.js"
OSRM_CACHE = EXTRACTED / "osrm_route_cache.json"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"

BOOK_COLORS = {
    "book01": "#c0392b",
    "book02": "#d68910",
    "book03": "#2471a3",
}

BOOKS = ["book01_curated.json", "book02_curated.json", "book03_curated.json"]

# Подписи для читателя карты (не внутренние коды куратора)
TYPE_LABELS = {
    "meet_key": "Встреча",
    "farewell_key": "Прощание",
    "combat": "Бой",
    "ambush": "Засада",
    "scavenge": "Поиск припасов",
    "meet": "Встреча",
    "shelter": "Ночёвка / база",
    "travel_start": "Отправление",
    "travel_arrive": "Прибытие",
    "vehicle": "Транспорт",
    "weather": "Погода",
    "air": "Перелёт",
    "sea": "Море",
    "medical": "Ранение",
    "trade": "Сделка",
    "recon": "Разведка",
    "family": "Родные в России",
    "other": "Эпизод",
}

IMPORTANCE_LABELS = {
    "key": "Главный момент",
    "major": "Важный момент",
    "normal": "",  # не показываем
}

EDGE_KIND_LABELS = {
    "causes": "привело к",
    "delays": "задержало",
    "reroutes": "сменило маршрут",
    "enables": "сделало возможным",
    "prevents": "предотвратило",
    "joins": "добавление в группу",
    "loses": "потеря",
    "changes_transport": "смена транспорта",
    "weather": "погода повлияла",
    "leads_to": "итог дальше по сюжету",
}

# Спутники для фильтра на карте
COMPANION_IDS = ("c-drika", "c-sam", "c-tiger", "c-jeff", "c-sox")

# Только микроточки одного двора/поля — не склеивать Юму с Уэлтоном
LOCALE_OF = {
    "p-tenth-hole": "p-coyote-waterhole",  # пост на том же гольф-клубе
    "p-yuma-county": "p-yuma-city",  # «округ» на карте = город Юма (не Уэлтон)
    "p-expo-inn-lufkin": "p-lufkin",  # мотель в том же Лафкине
}

ALWAYS_ROUTE = {
    "travel_start",
    "travel_arrive",
    "sea",
    "air",
    "vehicle",
    "scavenge",
    "trade",
    "weather",  # шторм в океане — точка на курсе, не «в стороне»
}
FAR_ROUTE = {"meet_key", "farewell_key", "shelter", "combat", "medical", "meet"}
MIN_HOP_KM = 1.2  # склеивать только почти ту же точку; Юма↔Уэлтон (~45 км) — отдельные

TRANSPORT_BY_TYPE = {
    "air": "air",
    "sea": "sea",
    "weather": "sea",
    "travel_start": "land",
    "travel_arrive": "land",
    "vehicle": "land",
    "scavenge": "land",
    "trade": "land",
}


def load_coords() -> dict[str, list[float]]:
    raw = json.loads((EXTRACTED / "coords_seed.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def path_km(coords: list) -> float:
    """Длина ломаной GeoJSON [[lon, lat], ...] в км."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1][0], coords[i - 1][1]
        lon2, lat2 = coords[i][0], coords[i][1]
        total += haversine_km(lat1, lon1, lat2, lon2)
    return round(total, 1)


def load_osrm_cache() -> dict:
    if OSRM_CACHE.exists():
        return json.loads(OSRM_CACHE.read_text(encoding="utf-8"))
    return {}


def save_osrm_cache(cache: dict) -> None:
    OSRM_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def osrm_drive(lon1: float, lat1: float, lon2: float, lat2: float, cache: dict) -> list[list[float]] | None:
    key = f"{lon1:.5f},{lat1:.5f};{lon2:.5f},{lat2:.5f}"
    if key in cache:
        return cache[key]
    url = OSRM_URL.format(coords=f"{lon1},{lat1};{lon2},{lat2}")
    req = urllib.request.Request(url, headers={"User-Agent": "IGH-map/0.3 (memorial map)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  OSRM fail {key}: {exc}")
        cache[key] = None
        return None
    if data.get("code") != "Ok" or not data.get("routes"):
        cache[key] = None
        return None
    coords = data["routes"][0]["geometry"]["coordinates"]
    cache[key] = coords
    time.sleep(0.12)
    return coords


def great_circle(lon1: float, lat1: float, lon2: float, lat2: float, n: int = 24) -> list[list[float]]:
    return [
        [lon1 + (lon2 - lon1) * i / n, lat1 + (lat2 - lat1) * i / n] for i in range(n + 1)
    ]


# Морские коридоры (lon, lat): «Мариетта» — Сев. море → вокруг Дании проливами → Балтика
# (в книге: «обогнули Данию и прошли проливами», затем «неподалеку от Готланда»)
# Точки держат фарватер: не резать Сконе, Эстонию и Испанию по суше.
SEA_LANES: dict[tuple[str, str], list[tuple[float, float]]] = {
    ("p-delfzijl", "p-gotland"): [
        (6.4, 53.75),  # выход из Эмса / Ваддензе
        (5.0, 54.8),  # Северное море
        (6.2, 56.3),  # к Скагерраку
        (7.8, 57.4),
        (10.5, 57.9),  # севернее Скагена
        (11.5, 56.7),  # Каттегат (середина)
        (12.55, 55.85),  # Зунд, западнее о. Вен
        (12.75, 55.55),  # южнее Вен / выход в Балтику (не через Сконе)
        (13.4, 55.25),  # южнее Мальмё, открытая Балтика
        (14.8, 55.35),
        (16.5, 56.2),
        (17.8, 56.9),  # подход к Готланду с юго-запада
    ],
    ("p-gotland", "p-kronstadt"): [
        (19.0, 58.15),  # севернее Готланда, открытая вода
        (20.8, 58.7),
        (22.8, 59.15),  # середина подхода к Финскому заливу
        (24.8, 59.45),
        (26.6, 59.65),  # ось залива, не по берегу Эстонии
        (28.2, 59.85),
        (29.2, 59.98),  # к Кронштадту по воде
    ],
    ("p-gotland", "p-kronstadt-hospital"): [
        (19.0, 58.15),
        (20.8, 58.7),
        (22.8, 59.15),
        (24.8, 59.45),
        (26.6, 59.65),
        (28.2, 59.85),
        (29.2, 59.98),
    ],
    # Атлантика «Проныры» — чуть южнее хорды, как типичный трек
    ("p-placentia-bay", "p-n-atlantic"): [
        (-48.0, 46.0),
        (-40.0, 44.5),
    ],
    # Через Гибралтарский пролив, не вдоль берега Португалии/Испании
    ("p-n-atlantic", "p-andalusia-coast"): [
        (-22.0, 39.5),
        (-15.0, 37.2),
        (-10.0, 36.0),  # западнее Кадиса, ещё Атлантика
        (-7.2, 35.95),  # к воронке пролива
        (-5.75, 35.97),  # середина Гибралтарского пролива
        (-4.95, 36.25),  # уже Средиземное море
    ],
}


def sea_path(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    from_hub: str,
    to_hub: str,
) -> list[list[float]]:
    """Ломаная по морю с промежуточными точками, без пересечения суши «по прямой»."""
    key = (from_hub, to_hub)
    wps = SEA_LANES.get(key)
    if wps is None:
        rev = (to_hub, from_hub)
        if rev in SEA_LANES:
            wps = list(reversed(SEA_LANES[rev]))
    pts: list[list[float]] = [[lon1, lat1]]
    chain = list(wps or []) + [(lon2, lat2)]
    for lon, lat in chain:
        prev = pts[-1]
        if abs(prev[0] - lon) < 1e-6 and abs(prev[1] - lat) < 1e-6:
            continue
        pts.extend(great_circle(prev[0], prev[1], lon, lat, n=10)[1:])
    return pts


def route_key(pid: str) -> str:
    """Canonical place id for hub/route (микрослияния только)."""
    return LOCALE_OF.get(pid, pid)


def point_for(pid: str, coords: dict) -> tuple[float, float]:
    """lat, lon for routing / hub."""
    canon = route_key(pid)
    lat, lon = coords[canon] if canon in coords else coords[pid]
    return lat, lon


def load_char_names() -> dict[str, str]:
    path = EXTRACTED / "characters.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        c["id"]: c.get("name_book") or c.get("name_full") or c["id"]
        for c in raw.get("characters", [])
    }


def load_spine_chapters() -> dict[str, dict]:
    path = SPINE / "chapters.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {c["chapter_id"]: c for c in raw.get("chapters", [])}


def load_igth_graph() -> dict:
    path = SPINE / "graph_igth.json"
    if not path.exists():
        return {"nodes": [], "edges": []}
    return json.loads(path.read_text(encoding="utf-8"))


def month_name_ru(m: int | None) -> str:
    names = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    return names.get(m or 0, "")


def main() -> None:
    coords = load_coords()
    char_names = load_char_names()
    places: dict[str, dict] = {}
    events: list[dict] = []
    edges: list[dict] = []

    for book_file in BOOKS:
        data = json.loads((EXTRACTED / book_file).read_text(encoding="utf-8"))
        book_id = data["book_id"]
        for p in data.get("places", []):
            pid = p["id"]
            if pid not in places:
                places[pid] = {**p, "books": [book_id]}
            else:
                if book_id not in places[pid]["books"]:
                    places[pid]["books"].append(book_id)
                for k in ("name_book", "name_map", "kind", "pov_default", "approx", "on_route"):
                    if k in p and p[k] is not None:
                        places[pid][k] = p[k]
        for e in data.get("events", []):
            events.append({**e, "book_id": book_id})
        for edge in data.get("edges", []):
            edges.append({**edge, "book_id": book_id})

    spine = load_spine_chapters()
    igth_graph = load_igth_graph()

    # День сюжета: +1 на новую главу + календарь из spine (IGTH)
    day = 0
    last_ch = None
    for e in events:
        ch = e.get("chapter_id")
        if ch != last_ch:
            day += 1
            last_ch = ch
        e["day"] = day
        sp = spine.get(ch) or {}
        e["date"] = sp.get("date") or ""
        e["time_of_day"] = sp.get("time") or ""
        e["weekday"] = sp.get("weekday") or ""
        e["spine_location"] = sp.get("location") or ""
        e["spine_seq"] = sp.get("seq")
        e["calendar_label"] = ""
        if e["date"]:
            parts = [e["date"]]
            if e["weekday"]:
                parts.append(e["weekday"])
            if e["time_of_day"]:
                parts.append(e["time_of_day"])
            e["calendar_label"] = ", ".join(parts)
        e["pivots"] = sp.get("pivots") or []

    def place_on_route(pid: str) -> bool:
        p = places.get(pid) or {}
        if p.get("on_route") is False or p.get("kind") == "goal":
            return False
        if pid.endswith("-goal") or pid.endswith("-reject"):
            return False
        return True

    # --- Hubs: один маркер на locale или place ---
    hubs: dict[str, dict] = {}
    for e in events:
        pid = e.get("place_id")
        if not pid or pid not in coords:
            continue
        if not place_on_route(pid) and (places.get(pid) or {}).get("kind") == "goal":
            continue
        hk = route_key(pid)
        if hk not in hubs:
            lat, lon = point_for(pid, coords)
            pl = places.get(hk) or places.get(pid) or {}
            hubs[hk] = {
                "id": hk,
                "lat": lat,
                "lon": lon,
                "name": pl.get("name_book", hk),
                "name_map": pl.get("name_map", ""),
                "events": [],
                "books": set(),
                "pov": set(),
            }
        hubs[hk]["events"].append(e["id"])
        hubs[hk]["books"].add(e.get("book_id"))
        hubs[hk]["pov"].add(e.get("pov", "protagonist"))

    # Index events by id for payload
    by_id = {e["id"]: e for e in events}

    hub_features = []
    for hk, h in hubs.items():
        evs = [by_id[i] for i in h["events"] if i in by_id]
        days = [e["day"] for e in evs]
        # представительское событие — ключевое или последнее
        key_evs = [e for e in evs if e.get("importance") == "key"]
        rep = key_evs[-1] if key_evs else evs[-1]
        hub_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
                "properties": {
                    "id": hk,
                    "name": h["name"],
                    "name_map": h["name_map"],
                    "event_ids": [e["id"] for e in evs],
                    "event_count": len(evs),
                    "day_min": min(days) if days else None,
                    "day_max": max(days) if days else None,
                    "books": sorted(h["books"]),
                    "book_colors": [BOOK_COLORS.get(b, "#888") for b in sorted(h["books"])],
                    "pov": sorted(h["pov"]),
                    "rep_title": rep.get("title"),
                    "rep_type": rep.get("type"),
                    "rep_importance": rep.get("importance"),
                },
            }
        )

    # Full event list for panel (coords = hub, без веера)
    event_list = []
    for e in events:
        pid = e.get("place_id")
        if not pid or pid not in coords:
            continue
        if (places.get(pid) or {}).get("kind") == "goal":
            continue
        lat, lon = point_for(pid, coords)
        cids = e.get("characters") or []
        people = [char_names.get(cid, cid) for cid in cids]
        # не светить сырые c-* если имени нет
        people = [p for p in people if not str(p).startswith("c-")]
        imp = e.get("importance", "normal")
        pl = places.get(route_key(pid)) or places.get(pid) or {}
        event_list.append(
            {
                "id": e["id"],
                "place_id": pid,
                "hub_id": route_key(pid),
                "place_name": pl.get("name_book", pid),
                "title": e.get("title", e["id"]),
                "summary": e.get("summary", ""),
                "sought": e.get("sought", ""),
                "outcome": e.get("outcome", ""),
                "type": e.get("type", "other"),
                "type_label": TYPE_LABELS.get(e.get("type", "other"), "Эпизод"),
                "importance": imp,
                "importance_label": IMPORTANCE_LABELS.get(imp, ""),
                "pov": e.get("pov", "protagonist"),
                "pov_label": "Родные в России"
                if e.get("pov") == "family_ru"
                else "Путь героя",
                "book_id": e.get("book_id"),
                "book_label": {
                    "book01": "Книга 1",
                    "book02": "Книга 2",
                    "book03": "Книга 3",
                }.get(e.get("book_id", ""), e.get("book_id", "")),
                "chapter_id": e.get("chapter_id"),
                "people": people,
                "character_ids": cids,
                "day": e["day"],
                "date": e.get("date", ""),
                "time_of_day": e.get("time_of_day", ""),
                "weekday": e.get("weekday", ""),
                "calendar_label": e.get("calendar_label", ""),
                "spine_location": e.get("spine_location", ""),
                "spine_seq": e.get("spine_seq"),
                "pivots": e.get("pivots") or [],
                "book_color": BOOK_COLORS.get(e.get("book_id", ""), "#888"),
                "lat": lat,
                "lon": lon,
            }
        )

    # Порядок для prev/next
    event_list.sort(key=lambda x: (x["day"], x["book_id"] or "", x["chapter_id"] or "", x["id"]))
    for i, e in enumerate(event_list):
        e["prev_id"] = event_list[i - 1]["id"] if i > 0 else None
        e["next_id"] = event_list[i + 1]["id"] if i + 1 < len(event_list) else None
        e["prev_title"] = event_list[i - 1]["title"] if i > 0 else None
        e["next_title"] = event_list[i + 1]["title"] if i + 1 < len(event_list) else None

    # --- Route stops: смена локали / дальние прыжки ---
    candidates = [
        e
        for e in events
        if e.get("pov") == "protagonist"
        and e.get("on_route") is not False
        and e.get("place_id") in coords
        and place_on_route(e["place_id"])
        and e.get("type") in ALWAYS_ROUTE | FAR_ROUTE
        and e.get("importance") in {"key", "major"}
    ]

    route_meta = []
    last_rk = None
    last_ll = None
    for e in candidates:
        pid = e["place_id"]
        rk = route_key(pid)
        lat, lon = point_for(pid, coords)
        et = e.get("type", "")
        if rk == last_rk:
            # тот же хаб: обновить титул/отбытие, но day = день ПРИБЫТИЯ
            # (иначе to_day у сегмента уезжает вперёд → линия «появляется» только через N дней)
            if route_meta:
                prev = route_meta[-1]
                prev["depart_day"] = e["day"]
                if et in ALWAYS_ROUTE or (
                    e.get("importance") in {"key", "major"}
                    and et in FAR_ROUTE
                ):
                    prev.update(
                        {
                            "event_id": e["id"],
                            "title": e.get("title"),
                            "type": et,
                            "transport": TRANSPORT_BY_TYPE.get(
                                et, prev.get("transport") or "land"
                            ),
                        }
                    )
            continue
        if last_ll is not None and et in FAR_ROUTE:
            if haversine_km(last_ll[0], last_ll[1], lat, lon) < MIN_HOP_KM:
                continue
        route_meta.append(
            {
                "hub_id": rk,
                "place_id": pid,
                "event_id": e["id"],
                "title": e.get("title"),
                "book_id": e.get("book_id"),
                "type": et,
                "day": e["day"],
                "depart_day": e["day"],
                "transport": TRANSPORT_BY_TYPE.get(et, "land"),
                "lon": lon,
                "lat": lat,
            }
        )
        last_rk = rk
        last_ll = (lat, lon)

    osrm_cache = load_osrm_cache()
    segment_features = []
    routed = 0
    fallback = 0
    print(f"Routing {max(0, len(route_meta) - 1)} hops ({len(route_meta)} stops)…")
    for i in range(len(route_meta) - 1):
        a, b = route_meta[i], route_meta[i + 1]
        # режим перехода: не тянуть «air» со старой авиа-остановки на следующий сухопутный хаб
        mode = b.get("transport") or "land"
        if b.get("type") == "air":
            mode = "air"
        elif a.get("type") == "air" and b.get("type") == "air":
            mode = "air"
        if b.get("type") in ("sea", "weather") or a.get("type") in ("sea", "weather"):
            mode = "sea"
        if b.get("transport") == "sea" or a.get("transport") == "sea":
            mode = "sea"
        # океанские хабы всегда морем (не гонять OSRM через Испанию)
        ocean = {"p-n-atlantic", "p-placentia-bay", "p-andalusia-coast", "p-cadiz-funnel"}
        if a.get("hub_id") in ocean or b.get("hub_id") in ocean:
            mode = "sea"
        vessel = None
        if mode == "land":
            geom = osrm_drive(a["lon"], a["lat"], b["lon"], b["lat"], osrm_cache)
            if geom and len(geom) >= 2:
                routed += 1
            else:
                geom = [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]
                fallback += 1
                mode = "land_approx"
        elif mode == "sea":
            geom = sea_path(
                a["lon"], a["lat"], b["lon"], b["lat"], a["hub_id"], b["hub_id"]
            )
            # «Мариетта»: Дельфзийль → Готланд → Кронштадт
            marietta_hubs = {
                "p-delfzijl",
                "p-gotland",
                "p-kronstadt",
                "p-kronstadt-hospital",
            }
            if a["hub_id"] in marietta_hubs and b["hub_id"] in marietta_hubs:
                vessel = "Мариетта"
        else:
            geom = great_circle(a["lon"], a["lat"], b["lon"], b["lat"])
        dist = path_km(geom)
        props = {
            "from": a["hub_id"],
            "to": b["hub_id"],
            "from_title": a["title"],
            "to_title": b["title"],
            # from = день отбытия с хаба A; to = день прибытия на B
            "from_day": a.get("depart_day", a["day"]),
            "to_day": b["day"],
            "transport": mode,
            "book_id": b.get("book_id"),
            "distance_km": dist,
        }
        if vessel:
            props["vessel"] = vessel
        segment_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": geom},
                "properties": props,
            }
        )
    save_osrm_cache(osrm_cache)

    for s in route_meta:
        s["cumulative_km"] = 0.0
    cum = 0.0
    for i, seg in enumerate(segment_features):
        cum += float(seg["properties"].get("distance_km") or 0)
        if i + 1 < len(route_meta):
            route_meta[i + 1]["cumulative_km"] = round(cum, 1)

    total_km = round(cum, 1)

    stops_out = [{k: v for k, v in s.items() if k not in ("lon", "lat")} for s in route_meta]

    title_by_id = {e["id"]: e["title"] for e in event_list}
    hub_by_event = {e["id"]: e["hub_id"] for e in event_list}
    day_by_id = {e["id"]: e["day"] for e in event_list}
    cal_by_id = {e["id"]: e.get("calendar_label", "") for e in event_list}

    # chapter → лучшее curated-событие для привязки IGTH-графа
    by_chapter: dict[str, list[dict]] = {}
    for e in event_list:
        by_chapter.setdefault(e.get("chapter_id") or "", []).append(e)

    def pick_for_chapter(chapter_id: str | None) -> str | None:
        if not chapter_id:
            return None
        evs = by_chapter.get(chapter_id) or []
        if not evs:
            return None
        keys = [x for x in evs if x.get("importance") == "key"]
        majors = [x for x in evs if x.get("importance") == "major"]
        return (keys or majors or evs)[0]["id"]

    edges_out = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_edge(edge: dict) -> None:
        fr, to = edge.get("from"), edge.get("to")
        if not fr or not to or fr not in title_by_id or to not in title_by_id:
            return
        pair = (fr, to)
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        kind = edge.get("kind", "leads_to")
        edges_out.append(
            {
                "id": edge.get("id"),
                "from": fr,
                "to": to,
                "kind": kind,
                "kind_label": EDGE_KIND_LABELS.get(kind, kind),
                "summary": edge.get("summary", ""),
                "book_id": edge.get("book_id"),
                "source": edge.get("source", "curated"),
                "from_title": title_by_id.get(fr, fr),
                "to_title": title_by_id.get(to, to),
                "from_hub": hub_by_event.get(fr),
                "to_hub": hub_by_event.get(to),
                "from_day": day_by_id.get(fr),
                "to_day": day_by_id.get(to),
                "from_calendar": cal_by_id.get(fr, ""),
                "to_calendar": cal_by_id.get(to, ""),
            }
        )

    for edge in edges:
        add_edge({**edge, "source": "curated"})

    igth_linked = 0
    for edge in igth_graph.get("edges", []):
        fr = pick_for_chapter(edge.get("from_chapter_id"))
        to = pick_for_chapter(edge.get("to_chapter_id"))
        if not fr or not to or fr == to:
            continue
        add_edge(
            {
                "id": edge.get("id"),
                "from": fr,
                "to": to,
                "kind": edge.get("kind", "leads_to"),
                "summary": edge.get("summary", ""),
                "source": "igth_graph",
            }
        )
        igth_linked += 1

    companions = []
    for cid in COMPANION_IDS:
        name = char_names.get(cid)
        if not name:
            continue
        ev_ids = [e["id"] for e in event_list if cid in (e.get("character_ids") or [])]
        if not ev_ids:
            continue
        companions.append(
            {
                "id": cid,
                "name": name,
                "event_ids": ev_ids,
                "event_count": len(ev_ids),
            }
        )

    # Календарный скелет для таймлайна (сжатый)
    spine_days = []
    for cid, sp in sorted(spine.items(), key=lambda x: x[1].get("seq") or 0):
        # day index = порядок появления chapter среди наших событий; иначе seq
        day_idx = next((e["day"] for e in event_list if e.get("chapter_id") == cid), None)
        spine_days.append(
            {
                "chapter_id": cid,
                "seq": sp.get("seq"),
                "day": day_idx,
                "date": sp.get("date"),
                "time": sp.get("time"),
                "weekday": sp.get("weekday"),
                "location": sp.get("location"),
                "pov": sp.get("pov"),
                "calendar_label": ", ".join(
                    p
                    for p in [sp.get("date"), sp.get("weekday"), sp.get("time")]
                    if p
                ),
                "summary": (sp.get("summary") or "")[:180],
            }
        )

    # Список остановок маршрута с календарём
    stops_ui = []
    for s in stops_out:
        eid = s.get("event_id")
        ev = next((x for x in event_list if x["id"] == eid), None)
        stops_ui.append(
            {
                **s,
                "calendar_label": (ev or {}).get("calendar_label", ""),
                # day = прибытие на хаб; не подменять днём позднего события на той же точке
                "day": s.get("day"),
                "depart_day": s.get("depart_day", s.get("day")),
                "place_name": (ev or {}).get("place_name", ""),
            }
        )

    payload = {
        "meta": {
            "title": "Я! Еду! Домой! — карта маршрута",
            "hubs": len(hub_features),
            "events": len(event_list),
            "route_stops": len(stops_out),
            "route_segments": len(segment_features),
            "osrm_routed": routed,
            "osrm_fallback": fallback,
            "day_max": day,
            "route_total_km": total_km,
            "edges": len(edges_out),
            "igth_edges_linked": igth_linked,
            "spine_chapters": len(spine),
        },
        "hubs": {"type": "FeatureCollection", "features": hub_features},
        "events": event_list,
        "route": {
            "type": "FeatureCollection",
            "features": segment_features,
            "properties": {
                "name": "protagonist_route",
                "stops": stops_ui,
                "total_km": total_km,
            },
        },
        "edges": edges_out,
        "companions": companions,
        "spine": spine_days,
        "book_colors": BOOK_COLORS,
        "type_labels": TYPE_LABELS,
        "edge_kind_labels": EDGE_KIND_LABELS,
    }

    MAP_DIR.mkdir(parents=True, exist_ok=True)
    (MAP_DIR / "geo").mkdir(exist_ok=True)
    (MAP_DIR / "geo" / "hubs.geojson").write_text(
        json.dumps(payload["hubs"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (MAP_DIR / "geo" / "route.geojson").write_text(
        json.dumps(payload["route"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    OUT_JS.write_text(
        "window.MAP_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {OUT_JS} hubs={len(hub_features)} events={len(event_list)} "
        f"stops={len(stops_out)} osrm={routed} days=1..{day} "
        f"spine={len(spine)} edges={len(edges_out)} (+igth_linked={igth_linked})"
    )


if __name__ == "__main__":
    main()
