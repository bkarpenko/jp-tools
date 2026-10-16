#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ru_pass.py — лист русской редактуры для готового разбора (шаг 11 PIPELINE.md).

ЗАЧЕМ. Русский в разборе пишется рядом с английским, и на этом месте он
перенимает английский синтаксис; рядом с оригиналом калька выглядит верной.
Редактура поэтому идёт по отдельному листу, где у каждой единицы §6 есть
оригинал и русский — и нет английского. Второй довод — цена исправления:
ряд §6 вставлен в разбор в двух–пяти местах, и править их руками дорого;
`apply` заменяет строку во всех местах разом.

    python3 tools/jukugo/ru_pass.py extract <разбор>.md > ru.tsv
        Лист: ID, оригинал, текущий русский, пустой столбец «новый».
        Английского в листе нет намеренно.

    python3 tools/jukugo/ru_pass.py apply <разбор>.md ru.tsv
        Каждая строка листа, где «новый» заполнен и отличается от текущего:
        «текущий» заменяется на «новый» во всём файле — в §6 и везде, куда ряд
        вставлен. Печатает, что и сколько раз заменено. Файл переписывается
        на месте; после — check_glosses.py.

Строка ищется вместе с ёлочками («…»), поэтому часть чужой строки не задевается.
Если текущий русский в файле не найден — это ошибка, и файл не меняется вовсе.
"""

import csv
import re
import sys

SEC6 = "§6. Единицы перевода"


def table_rows(text):
    """Ряды §6 как словари по заголовку таблицы: порядок столбцов не важен."""
    idx = text.find(SEC6)
    if idx == -1:
        sys.exit(f"ОШИБКА: в файле нет секции «{SEC6}».")
    header, rows = None, []
    for line in text[idx:].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            header = [c.upper() for c in cells]
            continue
        if set(cells[0]) <= set("-: "):
            continue
        rows.append(dict(zip(header, cells)))
    if not header or "RU" not in header:
        sys.exit("ОШИБКА: в шапке §6 нет столбца RU.")
    return rows


def strip_guillemets(s):
    s = s.strip()
    if s.startswith("«") and s.endswith("»"):
        s = s[1:-1]
    return s


def extract(path):
    text = open(path, encoding="utf-8").read()
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(["ID", "Оригинал", "Русский", "Новый"])
    for r in table_rows(text):
        ru = strip_guillemets(r.get("RU", ""))
        if ru:
            w.writerow([r.get("ID", ""), r.get("ОРИГИНАЛ", ""), ru, ""])


def apply(path, sheet):
    text = open(path, encoding="utf-8").read()
    with open(sheet, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    plan, errors = [], []
    owners = {}
    for r in rows:
        owners.setdefault((r.get("Русский") or "").strip(), []).append(r["ID"])
    for r in rows:
        old, new = (r.get("Русский") or "").strip(), (r.get("Новый") or "").strip()
        if not new or new == old:
            continue
        if "»" in new or "«" in new:
            errors.append(f"{r['ID']}: в новом русском ёлочки — внутри строки кавычки „…“")
            continue
        if len(owners.get(old, [])) > 1:
            print(f"  ВНИМАНИЕ {r['ID']}: тот же русский у рядов {', '.join(owners[old])} — "
                  "замена заденет все")
        n = text.count(f"«{old}»")
        if n == 0:
            errors.append(f"{r['ID']}: «{old[:50]}» в файле не найдено")
            continue
        plan.append((r["ID"], old, new, n))
    if errors:
        print("Файл не изменён:")
        for e in errors:
            print("  ОШИБКА", e)
        return 1
    for uid, old, new, n in plan:
        text = text.replace(f"«{old}»", f"«{new}»")
        print(f"{uid}: заменено мест — {n}")
    open(path, "w", encoding="utf-8").write(text)
    print(f"Переписано рядов: {len(plan)}. Дальше — check_glosses.py.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "extract":
        extract(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "apply":
        sys.exit(apply(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
        sys.exit(2)
