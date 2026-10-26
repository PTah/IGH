#!/usr/bin/env python3
"""Print compact signals from a chapter for curation."""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLACE_HINT = re.compile(
    r"(?:"
    r"улиц[аеуы]\s+[«\"]?[А-ЯЁA-Z][\w\-]+|"
    r"авеню\s+[«\"]?[А-ЯЁA-Z][\w\-]+|"
    r"роуд\s+[«\"]?[А-ЯЁA-Z][\w\-]+|"
    r"шоссе\s+[«\"]?[\w\-]+|"
    r"аэропорт\w*\s+[«\"]?[А-ЯЁA-Z][\w\-]*|"
    r"округ\w*\s+[А-ЯЁA-Z][\w\-]+|"
    r"штат\w*\s+[А-ЯЁA-Z][\w\-]+|"
    r"(?:город(?:е|а|у)?|посёлк\w*|поселк\w*|деревн\w*|порт\w*|мост\w*|школ\w*|магазин\w*|больниц\w*)\s+"
    r"[«\"]?[А-ЯЁA-Z][\w\-]+"
    r")"
)

PEOPLE = re.compile(
    r"\b(?:Дрик\w*|Сэм\w*|Джек\w*|Джефф\w*|Пабл\w*|Тереза\w*|Маша\w*|Волод\w*|Том\w*|Майк\w*|Тигр\w*)\b"
)

ACTION = re.compile(
    r"(?:зомби|мертвяк\w*|перестрел\w*|стрелял\w*|ранен\w*|поломк\w*|сломал\w*|"
    r"улетел\w*|рейс\w*|карантин\w*|подобрал\w*|спас\w*|похорон\w*|"
    r"шторм\w*|ураган\w*|штормов\w*|топлив\w*|бензин\w*)",
    re.I,
)


def main() -> None:
    path = Path(sys.argv[1])
    t = path.read_text(encoding="utf-8")
    title = t.split("\n", 1)[0]
    print(f"FILE {path.name} chars={len(t)}")
    print(title)
    places = sorted(set(m.group(0) for m in PLACE_HINT.finditer(t)))
    people = sorted(set(m.group(0) for m in PEOPLE.finditer(t)))
    actions = sorted(set(m.group(0).lower() for m in ACTION.finditer(t)))
    print("PLACES:", "; ".join(places[:40]))
    print("PEOPLE:", "; ".join(people[:30]))
    print("ACTIONS:", "; ".join(actions[:40]))
    # first/last non-empty paras
    paras = [p.strip() for p in t.split("\n\n") if p.strip() and not p.startswith("#")]
    if paras:
        print("START:", paras[0][:280].replace("\n", " "))
        print("END:", paras[-1][:280].replace("\n", " "))


if __name__ == "__main__":
    main()
