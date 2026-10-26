#!/usr/bin/env python3
"""Heuristic candidate extractor for toponyms in Cruz books (pass 1)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# Patterns that often introduce place names in Russian prose
CONTEXT_PATTERNS = [
    r"(?:в|во|из|от|до|к|ко|на|через|мимо|около|возле|у|под|над|по)\s+"
    r"([А-ЯЁA-Z][А-Яа-яёA-Za-z\-]+(?:\s+[А-ЯЁA-Z][А-Яа-яёA-Za-z\-]+){0,3})",
    r"(?:город(?:е|а|у)?|городка|городке|посёлк[аеуи]|поселк[аеуи]|деревн[яиюе]|хутор[аеу]?|"
    r"штат[аеу]?|остров[аеу]?|полуостров[аеу]?|бухт[аеуы]|залив[аеу]?|порт[аеу]?|"
    r"аэропорт[аеу]?|вокзал[аеу]?|трасс[аеуы]|шоссе|улиц[аеуы]|проспект[аеу]?|"
    r"переул[оккае]|площад[ьи]|мост[аеу]?|реки?|речк[аиеу]|озера?|моря?)\s+"
    r"[«\"]?([А-ЯЁA-Z][А-Яа-яёA-Za-z\-]+(?:\s+[А-ЯЁA-Z][А-Яа-яёA-Za-z\-]+){0,3})",
    r"(?:штат|город|остров|полуостров)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
]

STOP = {
    "Я", "Он", "Она", "Они", "Мы", "Вы", "Ты", "Это", "То", "Так", "Но", "А",
    "И", "Или", "Если", "Когда", "Потом", "Тогда", "Сейчас", "Уже", "Ещё", "Еще",
    "Может", "Нужно", "Надо", "Можно", "Будет", "Было", "Были", "Есть", "Нет",
    "Да", "Во", "На", "По", "От", "До", "Из", "К", "Ко", "У", "Со", "Об", "За",
    "Под", "Над", "При", "Про", "Без", "Для", "Через", "Между", "После", "Перед",
    "Всё", "Все", "Всем", "Всего", "Ничего", "Никто", "Кто", "Что", "Где", "Куда",
    "Откуда", "Почему", "Зачем", "Как", "Какой", "Какая", "Какие", "Какое",
    "Свой", "Своя", "Своё", "Свое", "Свои", "Наш", "Наша", "Наше", "Наши",
    "Мой", "Моя", "Моё", "Мое", "Мои", "Твой", "Его", "Её", "Ее", "Их",
    "Один", "Одна", "Одно", "Одни", "Два", "Две", "Три", "Первый", "Второй",
    "Третий", "Последний", "Новый", "Старый", "Большой", "Маленький", "Хороший",
    "Плохой", "Долгий", "Короткий", "Дальний", "Ближний", "Правый", "Левый",
    "Северный", "Южный", "Восточный", "Западный", "Русский", "Американский",
    "Человек", "Люди", "Мужик", "Парень", "Женщина", "Девушка", "Ребёнок",
    "Ребенок", "Машина", "Автомобиль", "Грузовик", "Самолёт", "Самолет",
    "Корабль", "Лодка", "Оружие", "Винтовка", "Пистолет", "Патроны", "Еда",
    "Вода", "Дом", "Дома", "Домой", "Дорога", "Дороге", "Лес", "Леса", "Поле",
    "Небо", "Земля", "Земли", "Мир", "Война", "Смерть", "Жизнь", "Время",
    "День", "Ночь", "Утро", "Вечер", "Год", "Месяц", "Неделя", "Час", "Минута",
    "Километр", "Метр", "Миля", "Миль", "Север", "Юг", "Восток", "Запад",
    "Америка", "Россия", "США",  # keep these actually - remove from STOP
}

# Allow country/region level - remove from STOP if present
for w in ("Америка", "Россия", "США"):
    STOP.discard(w)

# Words that look like places but are often false positives after prepositions
FALSE_AFTER_PREP = {
    "Том", "Тому", "Те", "Тех", "Тем", "Этих", "Этим", "Этой", "Этого", "Этому",
    "Самом", "Самой", "Самого", "Конце", "Начале", "Середине", "Рядом", "Далеко",
    "Близко", "Впереди", "Позади", "Спереди", "Сзади", "Справа", "Слева",
    "Верху", "Низу", "Центре", "Края", "Краю", "Углу", "Угла", "Месте", "Места",
    "Пути", "Путь", "Ходу", "Хода", "Деле", "Случае", "Порядке", "Смысле",
    "Общем", "Целом", "Принципе", "Сути", "Факте", "Результате", "Итоге",
    "Конце", "Концов", "Любом", "Любом", "Каком", "Какой", "Том-то",
}


def candidates_from_text(text: str) -> Counter:
    counts: Counter = Counter()
    for pat in CONTEXT_PATTERNS:
        for m in re.finditer(pat, text):
            name = m.group(1).strip(" «»\"'")
            if not name or len(name) < 2:
                continue
            first = name.split()[0]
            if first in STOP or first in FALSE_AFTER_PREP:
                continue
            if name in STOP:
                continue
            # skip if all-caps short acronym weirdness except USA-like
            if re.fullmatch(r"[А-ЯЁ]{1,2}", name):
                continue
            counts[name] += 1
    return counts


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = root / "data" / "raw"
    out = root / "data" / "extracted"
    out.mkdir(parents=True, exist_ok=True)

    all_counts: Counter = Counter()
    per_book: dict[str, Counter] = {}
    per_chapter: dict[str, list] = defaultdict(list)

    for book_id in ("book01", "book02", "book03"):
        txt = (raw / f"{book_id}.txt").read_text(encoding="utf-8")
        c = candidates_from_text(txt)
        per_book[book_id] = c
        all_counts.update(c)

        ch_dir = raw / book_id
        if ch_dir.is_dir():
            for ch_file in sorted(ch_dir.glob("*.txt")):
                ch_text = ch_file.read_text(encoding="utf-8")
                title = ""
                if ch_text.startswith("# "):
                    title = ch_text.split("\n", 1)[0][2:].strip()
                ch_c = candidates_from_text(ch_text)
                if ch_c:
                    per_chapter[book_id].append(
                        {
                            "chapter_file": ch_file.name,
                            "title": title,
                            "top_candidates": ch_c.most_common(40),
                        }
                    )

    result = {
        "note": (
            "Автоматические кандидаты. Нужна ручная/LLM-вычитка по главам. "
            "Не финальный список локаций маршрута. "
            "Имена людей (Сэм, Дрика, Джек, Джефф…) — НЕ шум: см. characters.md / events meet_key. "
            "РФ-локации до прибытия героя (Кронштадт) — слой family_ru, не маршрут героя."
        ),
        "unique_candidates": len(all_counts),
        "top_global": all_counts.most_common(300),
        "per_book_top": {
            bid: per_book[bid].most_common(150) for bid in per_book
        },
        "per_chapter": per_chapter,
    }
    path = out / "place_candidates.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # also a readable markdown shortlist
    md_lines = [
        "# Кандидаты топонимов (авто, pass 1)",
        "",
        "Это **не** финальный список. Дальше — вычитка по главам.",
        "",
        "## Топ по всем книгам",
        "",
    ]
    for name, n in all_counts.most_common(200):
        md_lines.append(f"- {name} ({n})")
    (out / "place_candidates_top.md").write_text(
        "\n".join(md_lines) + "\n", encoding="utf-8"
    )
    print(f"Wrote {path} unique={len(all_counts)}")


if __name__ == "__main__":
    main()
