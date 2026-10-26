#!/usr/bin/env python3
"""Pull geographic hints from chapter titles (high-signal backbone of the route)."""
from __future__ import annotations

import json
import re
from pathlib import Path


def split_location(title: str) -> str | None:
    """Titles look like: '21 марта, среда, утро. Округ Юма, штат Аризона, США'."""
    if "." not in title:
        return None
    # Take everything after the last sentence-ish date part:
    # date/time often ends before a period that introduces place
    parts = [p.strip() for p in title.split(".") if p.strip()]
    if len(parts) < 2:
        return None
    # First part is usually date; rest may be location (sometimes multiple)
    loc = ". ".join(parts[1:]).strip()
    # Filter pure non-geo leftovers
    if not loc:
        return None
    if re.fullmatch(r"\d+.*", loc):
        return None
    return loc


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "extracted"
    rows = []
    unique = []
    seen = set()
    for book_id in ("book01", "book02", "book03"):
        toc = json.loads((out / f"{book_id}_toc.json").read_text(encoding="utf-8"))
        for ch in toc["chapters"]:
            loc = split_location(ch["title"])
            rows.append(
                {
                    "book_id": book_id,
                    "chapter_id": ch["id"],
                    "title": ch["title"],
                    "location_from_title": loc,
                }
            )
            if loc and loc not in seen:
                seen.add(loc)
                unique.append(loc)

    payload = {
        "unique_locations_from_titles": unique,
        "unique_count": len(unique),
        "chapters": rows,
    }
    (out / "locations_from_titles.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = ["# Локации из заголовков глав", "", f"Уникальных: **{len(unique)}**", ""]
    for i, loc in enumerate(unique, 1):
        md.append(f"{i}. {loc}")
    (out / "locations_from_titles.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"unique={len(unique)}")
    for loc in unique:
        print(f"  - {loc}")


if __name__ == "__main__":
    main()
