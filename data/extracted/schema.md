# Схема данных маршрута

## Два слоя карты (обязательно)

| Слой | `pov` | Что это |
|------|-------|---------|
| **Маршрут героя** | `protagonist` | Где был / что делал главный герой |
| **Параллель: родные в РФ** | `family_ru` | Главы про Москву, Подмосковье и т.п. **пока герой ещё не в России** |

Переключение: герой добирается до РФ примерно с **Кронштадта** (`book03-ch061`). До этой точки любые российские локации в заголовках — **не** точки его пути, а действия родных. На карте — другой цвет/фильтр слоя, не путать с «я еду домой».

## place (топоним / точка)

| Поле | Тип | Описание |
|------|-----|----------|
| id | string | `p-yuma`, `p-san-luis-az` |
| name_book | string | Как в тексте |
| name_map | string | Для геокодера / подписи |
| kind | enum | city, town, county, state, country, street, road, airport, port, bridge, landmark, region, sea, other |
| pov_default | enum | `protagonist` \| `family_ru` \| `both` |
| book_mentions | string[] | chapter_id |
| lat, lon | number? | После геокодирования |
| geocode_query | string? | Запрос к Maps API |
| notes | string? | |

## character (спутник / человек / животное — не топоним)

Имена вроде Сэм, Дрика, Тигр, Джек **не отбрасывать** как шум геопарсера. Они живут в `characters` и в `event` с высокой важностью.

| Поле | Тип |
|------|-----|
| id | `c-sam`, `c-drika`, `c-tiger`, … |
| name_book | Сэм, Дрика (Хендрике), Тигр, … |
| role | companion, family, ally, antagonist, local |
| species | human \| cat \| dog \| other (опционально) |
| importance | `key` \| `major` \| `minor` |
| first_meet | chapter_id + place_id |
| last_arc | chapter_id + place_id (прощание / гибель / расставание) |

См. `characters.md`. Ключевые спутники: **Сэм, Дрика, Тигр**.

## Граф причинности (второй слой данных)

См. `causality.md` и `graph_seed.json`.

У события дополнительно:

| Поле | Тип | Описание |
|------|-----|----------|
| impact | `critical` \| `major` \| `minor` \| `flavor` | Насколько изменило дальнейшее |
| caused_by | edge[] / from ids | Откуда пришли |
| causes | edge[] / to ids | На что повлияло |

Рёбра: `causes`, `delays`, `reroutes`, `enables`, `prevents`, `joins`, `loses`, `changes_transport`, `weather`, `leads_to`.

Примеры обязательной разметки: поломка → смена маршрута; ранение → потеря времени; шторм → снос курса; находка Тигра → `joins` + многократные `prevents`/`enables` по пути.

## leg (отрезок перемещения героя)

Только `pov: protagonist`.

| Поле | Тип | Описание |
|------|-----|----------|
| id | string | |
| from_place / to_place | string | place.id |
| transport | enum | walk, car, truck, rv, plane, boat, ship, train, other |
| companions | string[] | character.id |
| book | book01\|book02\|book03 | |
| chapters | string[] | |
| summary | string | |

## event (событие на карте)

| Поле | Тип | Описание |
|------|-----|----------|
| id | string | |
| place_id | string | |
| pov | `protagonist` \| `family_ru` | |
| type | enum | см. ниже |
| importance | `key` \| `major` \| `normal` | **key** — отдельная крупная иконка / обязательный попап |
| characters | string[] | кто участвовал |
| title | string | |
| summary | string | |
| book, chapter_id | | |
| approx | bool | Точка приблизительная |

### Типы событий (иконки)

- `meet_key` — **ключевая встреча** (Сэм, Дрика, Тигр…)
- `farewell_key` — прощание / похороны / расставание с ключевым спутником
- `combat` — боевое столкновение
- `ambush` — засада
- `scavenge` — поиск ресурсов / лут
- `meet` — обычная встреча с людьми
- `shelter` — ночёвка / база
- `travel_start` / `travel_arrive` — старт / прибытие
- `vehicle` — смена/поломка транспорта (**часто + ребро** `changes_transport` / `reroutes`)
- `weather` — шторм / непогода (**часто +** `weather` / `delays` / `reroutes`)
- `air` — авиация
- `sea` — море / порт
- `medical` — ранение / больница (**часто +** `delays`)
- `trade` — обмен / сделка
- `recon` — разведка
- `family` — событие параллельной линии родных в РФ
- `other`

### Обязательные key-события (черновик)

1. Встреча с **Дрикой** (Хендрике) — Юма, `book01-ch022`
2. Встреча / присоединение **Сэма** — район Джастисбёрга, Техас (`book02`)
3. Совместный путь Сэм + Дрика (США → Европа) — сегменты с `companions`
4. Гибель / похороны Дрики и Сэма — Кааг, Нидерланды (`book03`)
5. Прибытие героя в Россию — Кронштадт (`book03-ch061`) — с этой точки РФ-локации могут быть `protagonist`
