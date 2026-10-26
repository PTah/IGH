#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / "data" / "raw" / "book03"
names = [
    "Дрика", "Сэм", "Тигр", "Димитр", "Дитмир", "Вим", "Мариетт",
    "Маша", "Володя", "Игорь", "Крамцов", "Пантелеев", "Колено",
    "Дима", "Серж", "Рабинович", "Малага", "Готланд",
]
out = []
for f in sorted(root.glob("book03-ch*.txt")):
    t = f.read_text(encoding="utf-8")
    title = t.split("\n", 1)[0][2:].strip()
    peop = [n for n in names if n in t]
    flags = []
    for pat, lab in [
        (r"похорон", "bury"),
        (r"убил|убит|погиб", "kill"),
        (r"ранен", "wound"),
        (r"шторм|ураган", "storm"),
        (r"корабл|яхт|борт|судно|Мариетт", "ship"),
        (r"встретил|познакомил|подобрал", "meet"),
        (r"раб", "slave"),
    ]:
        if re.search(pat, t, re.I):
            flags.append(lab)
    out.append(f"{f.stem}|{title[:75]}|{'/'.join(peop[:10])}|{','.join(flags)}")

path = Path(__file__).resolve().parents[1] / "data" / "extracted" / "_book03_index.txt"
path.write_text("\n".join(out), encoding="utf-8")
print(path, len(out))
