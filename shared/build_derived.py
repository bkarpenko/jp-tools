#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_derived — сборка производных таблиц из первичных.

    python shared/build_derived.py            собрать всё
    python shared/build_derived.py --plain    без сжатия

**Чем производная таблица отличается от первичной.** Первичные (`kanji`, `luw2`,
`suw`, `writing`) выведены из корпуса BCCWJ скриптом `build_data.py` и пересобираются
только там, где лежит корпус — 1,4 ГБ, которых в облачной сессии нет. Производные
выведены из первичных и пересобираются где угодно, включая сессию. Править руками
нельзя ни те, ни другие, но цена пересборки у них разная.

**Зачем они вообще.** Общие объекты проекта переиспользуются в репозитории: таблицы
лежат в одном экземпляре, инструменты их импортируют. Но пакет скилла — отдельный
архив, устанавливаемый сам по себе, и общей файловой системы между установленными
скиллами нет. Значит каждому скиллу, которому нужны данные, они кладутся внутрь.
Отсюда правило: **в пакет едет выжимка под вопрос инструмента, а не первичный корпус.**
Первичный корпус несёт только частотка — ей нужны знаменатели и полный хвост.

## compounds — двузнаковые слова для шага 1 инструмента jukugo

Что нужно шагу 1: 語種, все леммы под одной записью, и есть ли слово в коротких
единицах. Для этого хватает шести полей по словам ровно из двух кандзи.

Почему ровно из двух: метод разбирает двузнаковые компаунды, а на трёх- и
четырёхзнаковых не проверен ни разу. Ответ «не проверено» считается по самому
запросу — число знаков видно без таблицы, — поэтому строки для них не нужны.

Хвост здесь обрезать нечем и незачем: у jukugo нет знаменателей, ранги и покрытие
он не считает. Это и отличает его от частотки, где хвост `luw2` обрезать запрещено.
"""
from __future__ import annotations

import gzip
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import rows, LUW2_TOTAL, SUW_TOTAL                 # noqa: E402

DATA = os.path.join(HERE, "data")


def n_kanji(s: str) -> int:
    return sum(1 for ch in s if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿")


def build_compounds() -> tuple:
    """Двузнаковые леммы и написания, которые к ним ведут."""
    lemmas = {}
    for r in rows("luw2"):
        if n_kanji(r[2]) == 2:
            lemmas.setdefault((r[2], r[1], r[4], r[3]), ["", ""])[0] = r[6]
    for r in rows("suw"):
        if n_kanji(r[2]) == 2:
            lemmas.setdefault((r[2], r[1], r[4], r[3]), ["", ""])[1] = r[6]

    # Написание -> лемма: запрос 刺身 не найдётся, лемма нормализована как 刺し身.
    # Своё же написание не храним — оно и так есть в первой таблице.
    forms = set()
    for s in rows("writing"):
        for part in s[6].split(","):
            form = part.rsplit("(", 1)[0].strip()
            if n_kanji(form) == 2 and form != s[1]:
                forms.add((form, s[1], s[0], s[4]))
    return lemmas, forms


def write(name: str, header: list, body, plain: bool) -> str:
    buf = io.StringIO()
    buf.write("\t".join(header) + "\n")
    n = 0
    for row in body:
        buf.write("\t".join(row) + "\n")
        n += 1
    raw = buf.getvalue().encode("utf-8")
    path = os.path.join(DATA, name + (".tsv" if plain else ".tsv.gz"))
    for old in (path, os.path.join(DATA, name + ".tsv"),
                os.path.join(DATA, name + ".tsv.gz")):
        if os.path.exists(old):
            os.remove(old)
    if plain:
        open(path, "wb").write(raw)
    else:
        with gzip.open(path, "wb", compresslevel=9) as f:
            f.write(raw)
    print(f"  {name:<12} {n:>7} строк   {os.path.getsize(path)/1e6:>6.2f} МБ   {path}")
    return n


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    plain = "--plain" in sys.argv
    print(f"первичные: luw2 {LUW2_TOTAL}, suw {SUW_TOTAL}\nпроизводные:")

    lemmas, forms = build_compounds()
    fmt = lambda x: ("%.3g" % float(x)) if x else ""
    n1 = write("compounds", ["lemma", "lForm", "wType", "pos", "luw2_pmw", "suw_pmw"],
               ([l, rd, w, p, fmt(a), fmt(b)]
                for (l, rd, w, p), (a, b) in sorted(lemmas.items())), plain)
    n2 = write("compforms", ["form", "lemma", "lForm", "freq"],
               (list(x) for x in sorted(forms)), plain)

    print("\nЧисла для констант в corpus.py:")
    print(f"  COMPOUNDS_TOTAL = {n1}")
    print(f"  COMPFORMS_TOTAL = {n2}")
    print("\nЕсли пересобирались первичные таблицы — эти числа изменились,"
          "\nи их надо перенести в corpus.py вместе с производными.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
