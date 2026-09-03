#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
goshu — шаг 1 разбора компаунда: 語種 и развилка по таблицам BCCWJ.

Зачем скрипт в инструменте, который был методом без кода. Шаг 1 отвечает
на три вопроса, и все три решаются таблицей, а не рассуждением:

  1. какое слово лежит под этой записью (под 気配 их два: ケハイ 和 и キハイ 漢);
  2. какое у него 語種 — колонка wType в suw/luw2;
  3. компаунд это или фраза — слово, которое есть в luw2 и отсутствует в suw,
     в коротких единицах распадается на морфемы (見た目 = 見 + た + 目).

Пока это было инструкцией, ответ зависел от того, что помнит модель, и первый
шаг разбора оказывался самым ненадёжным. Вывод скрипта одинаков при каждом
запуске и проверяется глазами — с этого и начинается контроль над методом.

Скрипт НЕ определяет место сложения. 経済 и 年金 оба размечены как 漢, но первое
собрано в Китае, а второе в Японии: ярлык 語種 говорит о слое лексики, а не
о происхождении слова. Место решается сравнением датировок двух словарей —
шаг 3 в PIPELINE.md.

Данные — производная таблица `compounds` (двузнаковые леммы) и `compforms`
(написания, ведущие к ним). Не первичный корпус: шагу 1 нужны шесть полей
по двузнаковым словам, а не 840 тысяч строк со всеми знаменателями. Собирается
`shared/build_derived.py`, устройство — там же в шапке.

Зависимость одна — shared/corpus.py, тот же слой доступа, что у частотки.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "shared"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus import rows                                        # noqa: E402

# Пометы 語種 в UniDic. 固 — имена собственные, отдельный разряд разметки.
WTYPE = {
    "和": ("和語", "исконно японское"),
    "漢": ("漢語", "китайского слоя"),
    "外": ("外来語", "заимствование из европейских языков"),
    "混": ("混種語", "смешанное"),
    "固": ("固有名詞", "имя собственное"),
}

# Японские пометы частей речи по-русски: уровень Бориса ~N3, японская
# грамматическая терминология в выдачу не идёт.
POS = {
    "名詞-普通名詞-一般": "существительное",
    "名詞-普通名詞-サ変可能": "существительное, образует глагол с する",
    "名詞-普通名詞-形状詞可能": "существительное, может быть определением",
    "名詞-普通名詞-サ変形状詞可能": "существительное, и глагол с する, и определение",
    "名詞-固有名詞-一般": "имя собственное",
    "形状詞-一般": "определительное слово (на -na)",
    "動詞-一般": "глагол",
    "副詞": "наречие",
}


def is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


def width(s: str) -> int:
    """Ширина строки в знакоместах терминала: кана и кандзи занимают два."""
    return sum(2 if (ch >= "\u1100" and (ch <= "\u115f" or "\u2e80" <= ch <= "\ua4cf"
                     or "\uac00" <= ch <= "\ud7a3" or "\uf900" <= ch <= "\ufaff"
                     or "\ufe30" <= ch <= "\ufe6f" or "\uff00" <= ch <= "\uff60"
                     or "\uffe0" <= ch <= "\uffe6")) else 1 for ch in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def lookup(word: str) -> dict:
    """Все леммы с этой записью. Ключ — чтение и 語種: часть речи между длинными
    и короткими единицами расходится (遭難: 一般 против サ変可能), и это разница
    разбора, а не два разных слова."""
    out = {}
    for r in rows("compounds"):
        if r[0] != word:
            continue
        rec = out.setdefault((r[1], r[2]), {"pos": r[3], "luw2": None, "suw": None})
        if r[4]:
            rec["luw2"] = float(r[4])
        if r[5]:
            rec["suw"] = float(r[5])
        # Часть речи берём от коротких единиц, если она там есть: они ближе
        # к слову, длинные единицы часто обобщают до 「一般」.
        if r[5]:
            rec["pos"] = r[3]
    return out


def by_writing(word: str) -> list:
    """Если запрос дан написанием, которого нет среди лемм: 刺身 -> 刺し身."""
    hits = [(int(r[3]), r[1], r[2]) for r in rows("compforms") if r[0] == word]
    hits.sort(reverse=True)
    return hits


def branch(wtype: str, in_suw: bool, in_luw2: bool,
           n_kanji: int = 2, has_kana: bool = False) -> list:
    """Что метод делает дальше. Возвращает строки вывода."""
    out = []
    if wtype in ("外", "混", "固"):
        out.append("ВЕТКА Ж: вне области инструмента.")
        out.append("  Метод разбирает сложение знаков и приставленную запись;")
        out.append("  смешанные, заимствования и имена собственные в неё не входят.")
        return out

    # Признак фразы читается только у двузнаковых и у слов с каной. Отсутствие
    # в suw у трёх- и четырёхзнакового ни о чём не говорит: короткие единицы
    # режут 一石二鳥 на 一石 + 二鳥 просто потому, что это сложение сложений.
    if in_luw2 and not in_suw and (has_kana or n_kanji <= 2):
        out.append("ВЕТКА Е (вероятно): слово есть в длинных единицах")
        out.append("  и отсутствует в коротких — в suw оно распадается на морфемы.")
        out.append("  Это признак фразы, а не компаунда (образец: 見た目 = 見 + た + 目).")
        out.append("  Проверить по 日国: если между знаками грамматический")
        out.append("  показатель, схема 構成 неприменима, и разбор на этом кончен.")
        out.append("")

    if wtype == "和":
        out.append("ВЕТКА В: 和語 — знаки к слову приставлены, а не сложены.")
        out.append("  Слово старше своей записи; разбирается соответствие знака")
        out.append("  и морфемы, а не связь знаков между собой.")
        out.append("  Ветка — плейсхолдер: см. PIPELINE.md, «Ветка В». Сказать это")
        out.append("  Борису и остановиться. Готовый разбор того же вида —")
        out.append("  tools/jukugo/docs/отложено/разборы/気配.md")
        return out

    out.append("ВЕТКА A или Б — по таблице не различаются.")
    out.append("  Ярлык 漢 говорит о слое лексики, а не о происхождении слова:")
    out.append("  経済 и 年金 оба 漢, но первое собрано в Китае, второе в Японии.")
    out.append("  Что из двух — решает шаг 3, сравнением старших датировок.")
    out.append("")
    out.append("ДАЛЬШЕ — шаг 2, такт 1: запросить статьи СЛОВА, обе.")
    out.append("  1. 日本国語大辞典 — с датированными примерами;")
    out.append("  2. hanyucidian.org — статья компаунда.")
    out.append("  Статьи ЗНАКОВ — такт 2, после того как ветка выбрана:")
    out.append("  hanyucidian по обоим знакам в любом случае, а для ветки Б")
    out.append("  ещё и японские сложения с теми же знаками, с датировками.")
    return out


def report(word: str) -> int:
    n_kanji = sum(1 for ch in word if is_kanji(ch))
    has_kana = any("ぁ" <= ch <= "ゖ" or "ァ" <= ch <= "ヺ" for ch in word)

    seen = lookup(word)
    if not seen:
        print(f"{word} — леммы с таким написанием в таблице двузнаковых нет.\n")
        hits = by_writing(word)
        if hits:
            print("Это написание принадлежит леммам:")
            for freq, lemma, reading in hits[:8]:
                print(f"  {lemma}  ({reading})  {freq} вхождений")
            print("\nЗапустить заново по нужной лемме.")
        else:
            print("И среди написаний оно не встречается. Проверить запись.")
        return 1

    print(f"{word} — шаг 1: 語種 и развилка\n")
    wr = max([width("чтение")] + [width(k[0]) for k in seen]) + 2
    print("  " + pad("чтение", wr) + pad("語種", 8)
          + pad("часть речи", 40) + "luw2 pmw   suw pmw")
    for (reading, wtype), rec in seen.items():
        name = WTYPE.get(wtype, (wtype, ""))[0]
        pmw_l = f"{rec['luw2']:.4g}" if rec["luw2"] is not None else "—"
        pmw_s = f"{rec['suw']:.4g}" if rec["suw"] is not None else "—"
        print("  " + pad(reading, wr) + pad(name, 8)
              + pad(POS.get(rec["pos"], rec["pos"]), 40)
              + f"{pmw_l:>8} {pmw_s:>9}")
    print()

    if n_kanji < 2:
        print(f"  ЗНАКОВ: {n_kanji}. Сложению не из чего складываться —")
        print("  это не компаунд. Данные выше даны справочно.\n")
    elif n_kanji > 2:
        print(f"  ЗНАКОВ: {n_kanji} → ВЕТКА Д, плейсхолдер.")
        print("  Разбирается деревом: сначала точка деления, потом тип узла.")
        print("  Ни одного такого слова не разобрано ни разу — решение записано,")
        print("  но не проверено (PIPELINE.md, «Ветка Д»).")
        print("  Данные выше верны, разбор на них не строится.\n")

    if len(seen) > 1:
        print("СТОП: под этой записью больше одного слова.")
        print("  Разбор приписывается паре (форма, значение), а не форме.")
        print("  Спросить, какое из них разбирается: ветки у них разные.\n")
        for (reading, wtype), rec in seen.items():
            head = branch(wtype, rec["suw"] is not None, rec["luw2"] is not None,
                          n_kanji, has_kana)[0]
            head = head.replace("ВЕТКА: ", "").replace("ПРИЗНАК: ", "")
            print(f"  {pad(reading, wr)}→ {head}")
        print("\n  Повторный запуск ничего не добавит — таблица уже всё сказала;")
        print("  дальше нужен ответ Бориса.")
        return 0

    (reading, wtype), rec = next(iter(seen.items()))
    name, gloss = WTYPE.get(wtype, (wtype, "разряд не опознан"))
    print(f"  語種 = {name} ({gloss})\n")
    for line in branch(wtype, rec["suw"] is not None, rec["luw2"] is not None,
                       n_kanji, has_kana):
        print(line)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__.strip())
        print("\nЗапуск:  python tools/jukugo/goshu.py 遭難")
        return 2
    bad = 0
    for i, word in enumerate(args):
        if i:
            print("\n" + "─" * 72 + "\n")
        bad += report(word)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
