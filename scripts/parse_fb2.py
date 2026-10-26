#!/usr/bin/env python3
"""Extract plain text and chapter structure from FictionBook 2.0 files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from defusedxml.ElementTree import fromstring as xml_fromstring
except ImportError:  # локальные доверенные FB2; pip install defusedxml — по желанию
    from xml.etree.ElementTree import fromstring as xml_fromstring

FB_NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}


def detect_encoding(raw: bytes) -> str:
    m = re.search(rb"encoding=[\"']([^\"']+)[\"']", raw[:300])
    if not m:
        return "utf-8"
    enc = m.group(1).decode("ascii", errors="ignore").lower()
    if enc in ("windows-1251", "cp1251"):
        return "cp1251"
    return enc


def local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def text_of(el: ET.Element | None) -> str:
    if el is None:
        return ""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(text_of(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def title_text(sec: ET.Element) -> str:
    for child in sec:
        if local(child.tag) == "title":
            return " ".join(text_of(child).split())
    return ""


def walk_sections(
    sec: ET.Element, depth: int, chapters: list[dict], book_id: str
) -> None:
    title = title_text(sec)
    paras: list[str] = []
    for child in sec:
        tag = local(child.tag)
        if tag == "p":
            t = " ".join(text_of(child).split())
            if t:
                paras.append(t)
        elif tag == "subtitle":
            t = " ".join(text_of(child).split())
            if t:
                paras.append(f"## {t}")
        elif tag == "empty-line":
            paras.append("")
        elif tag == "poem":
            t = " ".join(text_of(child).split())
            if t:
                paras.append(t)
    idx = len(chapters)
    chapters.append(
        {
            "id": f"{book_id}-ch{idx:03d}",
            "depth": depth,
            "title": title,
            "paragraph_count": len([p for p in paras if p]),
            "text": "\n\n".join(paras),
        }
    )
    for child in sec:
        if local(child.tag) == "section":
            walk_sections(child, depth + 1, chapters, book_id)


def parse_fb2(path: Path, book_id: str) -> dict:
    raw = path.read_bytes()
    enc = detect_encoding(raw)
    text = raw.decode(enc)
    # Drop binary blobs that break XML parsers in some FB2 dumps
    text = re.sub(
        r"<binary[^>]*>.*?</binary>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if len(text) > 80_000_000:
        raise SystemExit(f"FB2 too large: {path} ({len(text)} chars)")
    root = xml_fromstring(text)

    meta = {"source": str(path), "encoding": enc, "title": "", "authors": []}
    for el in root.iter():
        if local(el.tag) == "book-title" and not meta["title"]:
            meta["title"] = " ".join(text_of(el).split())
        if local(el.tag) == "author":
            fn = ln = ""
            for c in el:
                if local(c.tag) == "first-name":
                    fn = (c.text or "").strip()
                if local(c.tag) == "last-name":
                    ln = (c.text or "").strip()
            name = f"{fn} {ln}".strip()
            if name and name not in meta["authors"]:
                meta["authors"].append(name)

    chapters: list[dict] = []
    for el in root.iter():
        if local(el.tag) != "body":
            continue
        body_name = el.attrib.get("name", "main")
        if body_name and body_name.lower() not in ("", "main"):
            # skip notes bodies for place extraction pass 1; keep main only
            if body_name.lower() in ("notes", "footnotes"):
                continue
        for child in el:
            if local(child.tag) == "section":
                walk_sections(child, 0, chapters, book_id)
        break  # first main body only

    full_text = "\n\n".join(
        (f"# {ch['title']}\n\n{ch['text']}" if ch["title"] else ch["text"])
        for ch in chapters
    )
    return {
        "book_id": book_id,
        "meta": meta,
        "chapters": [
            {
                "id": ch["id"],
                "depth": ch["depth"],
                "title": ch["title"],
                "paragraph_count": ch["paragraph_count"],
            }
            for ch in chapters
        ],
        "full_text": full_text,
        "chapters_full": chapters,
    }


def main() -> int:
    import argparse
    import os

    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(
        description="Parse trilogy FB2 into data/raw and data/extracted"
    )
    ap.add_argument(
        "--books-dir",
        type=Path,
        default=os.environ.get("IGH_BOOKS_SRC") or None,
        help="Directory with FB2 files (or set IGH_BOOKS_SRC)",
    )
    args = ap.parse_args()
    if not args.books_dir:
        print(
            "Укажите каталог с FB2: --books-dir PATH или env IGH_BOOKS_SRC",
            file=sys.stderr,
        )
        return 2
    src_dir = Path(args.books_dir)
    out_raw = root / "data" / "raw"
    out_ext = root / "data" / "extracted"
    out_raw.mkdir(parents=True, exist_ok=True)
    out_ext.mkdir(parents=True, exist_ok=True)

    books = [
        ("book01", "01 - Я еду домой!.fb2"),
        ("book02", "02 - От чужих берегов.fb2"),
        ("book03", "03 - Те, кто выжил.fb2"),
    ]
    index = []
    for book_id, name in books:
        path = src_dir / name
        if not path.exists():
            print(f"MISSING: {path}", file=sys.stderr)
            return 1
        print(f"Parsing {name} ...")
        data = parse_fb2(path, book_id)
        txt_path = out_raw / f"{book_id}.txt"
        toc_path = out_ext / f"{book_id}_toc.json"
        txt_path.write_text(data["full_text"], encoding="utf-8")
        toc = {
            "book_id": data["book_id"],
            "meta": data["meta"],
            "chapters": data["chapters"],
            "char_count": len(data["full_text"]),
        }
        toc_path.write_text(
            json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # per-chapter files for easier reading
        ch_dir = out_raw / book_id
        ch_dir.mkdir(exist_ok=True)
        for ch in data["chapters_full"]:
            (ch_dir / f"{ch['id']}.txt").write_text(
                (f"# {ch['title']}\n\n" if ch["title"] else "") + ch["text"],
                encoding="utf-8",
            )
        rel_txt = f"data/raw/{book_id}.txt"
        index.append(
            {
                "book_id": book_id,
                "title": data["meta"]["title"],
                "chapters": len(data["chapters"]),
                "chars": len(data["full_text"]),
                "txt": rel_txt,
            }
        )
        print(
            f"  title={data['meta']['title']!r} chapters={len(data['chapters'])} "
            f"chars={len(data['full_text'])}"
        )
    (out_ext / "books_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
