#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пересборка базы data/ из сырых выгрузок BCCWJ.

В обычной работе не нужен: база уже собрана и лежит в data/. Запускается
только если корпус обновился или таблицы повреждены.

    python build_data.py                 # собрать в data/
    python build_data.py --plain         # без сжатия: вдвое быстрее чтение, вчетверо объём

Исходники (пути править под свою машину, см. CORPUS_DIR и TABLES_DIR):
  BCCWJ_frequencylist_suw_ver1_1.tsv     77 МБ
  BCCWJ_frequencylist_luw2_ver1_1.tsv   355 МБ
  BCCWJ_CharacterTable.tsv                4,7 МБ   (конвертация .xlsx -> .tsv)
  BCCWJ_WritingFormTable.tsv             19 МБ     (конвертация .xlsx -> .tsv)

Обе таблицы знаков и написаний BCCWJ раздаёт в .xlsx; openpyxl парсит их
на два порядка медленнее TSV (47 и 89 секунд против долей секунды), поэтому
здесь ожидается уже сконвертированный TSV.
"""

from __future__ import annotations

import gzip
import os
import sys

# Пути под свою машину. Переменные окружения нужны, чтобы гонять сборку
# из другого окружения (Cowork монтирует те же папки по другим путям),
# не правя файл.
CORPUS_DIR = os.environ.get(
    "JP_FREQ_CORPUS",
    r"C:\Users\bkarp\Yandex.Disk\Personal\Japanese\Корпуса\BCCWJ")
TABLES_DIR = os.environ.get(
    "JP_FREQ_TABLES", r"C:\Users\bkarp\development\bccwj-tools")
OUT = os.environ.get(
    "JP_FREQ_OUT_DATA",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

REGISTERS = ["PB", "PM", "PN", "LB", "OW", "OT", "OP", "OB", "OC", "OY", "OV", "OL", "OM"]
# индекс pmw-колонки каждого регистра в исходных 80 колонках частотного списка
REG_PMW = {"PB": 10, "PM": 13, "PN": 16, "LB": 19, "OW": 22, "OT": 25, "OP": 28,
           "OB": 31, "OC": 34, "OY": 37, "OV": 40, "OL": 43, "OM": 46}

PLAIN = "--plain" in sys.argv


def sink(name: str):
    """Открывает data/<name>.tsv[.gz] на запись."""
    path = os.path.join(OUT, name + ".tsv")
    if PLAIN:
        return open(path, "w", encoding="utf-8", newline=""), path
    return gzip.open(path + ".gz", "wt", encoding="utf-8", newline="", compresslevel=9), path + ".gz"


def num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0


def build_words(src: str, name: str):
    """Частотный список: 80 колонок -> 8.

    Раньше 13 регистровых троек сворачивались в охват и топ-3 — два числа,
    из которых нельзя построить профиль по жанрам. Теперь сохраняется pmw
    каждого непустого регистра: `PB12.3,LB9.14,OB7.2`. Охват и тройка лидеров
    из этого выводятся, поэтому отдельными колонками не дублируются.

    Стоит это +2,6 МБ в сжатом виде на 842 тысячи строк — три значащие цифры
    для столбиковой диаграммы избыточны и так.
    """
    out, path = sink(name)
    n = 0
    with open(src, encoding="utf-8", newline="") as f, out as o:
        f.readline()
        o.write("rank\tlForm\tlemma\tpos\twType\tfreq\tpmw\tрег_pmw\n")
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 47:
                continue
            regs = ",".join(r + "%.3g" % num(c[i])
                            for r, i in REG_PMW.items() if num(c[i]) > 0)
            o.write(f"{c[0]}\t{c[1]}\t{c[2]}\t{c[3]}\t{c[5]}\t{c[6]}\t"
                    f"{float(c[7]):.4f}\t{regs}\n")
            n += 1
    print(f"{path}: {n} строк, {os.path.getsize(path)/1e6:.2f} МБ")


def build_kanji(src: str, name: str):
    """Таблица знаков: только кандзи (字種 = 漢), плюс ранг и кумулятивное покрытие."""
    rows = []
    with open(src, encoding="utf-8", newline="") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 5 or c[2] != "漢":
                continue
            forms = "/".join((c[5] if len(c) > 5 else "").split("/")[:20])
            rows.append((c[0], int(c[3]), float(c[4]), forms))
    rows.sort(key=lambda r: -r[1])
    total = sum(r[1] for r in rows)
    out, path = sink(name)
    cum = 0
    with out as o:
        o.write("ранг\tкандзи\tfreq\tpmw\tкум%\tнаписания\n")
        for i, (ch, fr, pmw, forms) in enumerate(rows, 1):
            cum += fr
            o.write(f"{i}\t{ch}\t{fr}\t{pmw:.4f}\t{100*cum/total:.3f}\t{forms}\n")
    print(f"{path}: {len(rows)} кандзи, {total} вхождений, "
          f"{os.path.getsize(path)/1e6:.2f} МБ")
    print(f"  -> KANJI_TOTAL = {len(rows)}, KANJI_TOKENS = {total} в corpus.py")


def build_writing(src: str, name: str):
    """Таблица написаний: лемма -> её реальные письменные формы с частотами."""
    out, path = sink(name)
    n = 0
    with open(src, encoding="utf-8", newline="") as f, out as o:
        f.readline()
        o.write("чтение\tлемма\tpos\twType\tfreq\tформ\tнаписания\n")
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 9:
                continue
            o.write(f"{c[0]}\t{c[1]}\t{c[2]}\t{c[4]}\t{c[6]}\t{c[7]}\t{c[8]}\n")
            n += 1
    print(f"{path}: {n} строк, {os.path.getsize(path)/1e6:.2f} МБ")


BUILDERS = {
    "kanji":   (build_kanji,   TABLES_DIR, "BCCWJ_CharacterTable.tsv"),
    "writing": (build_writing, TABLES_DIR, "BCCWJ_WritingFormTable.tsv"),
    "suw":     (build_words,   CORPUS_DIR, "BCCWJ_frequencylist_suw_ver1_1.tsv"),
    "luw2":    (build_words,   CORPUS_DIR, "BCCWJ_frequencylist_luw2_ver1_1.tsv"),
}

if __name__ == "__main__":
    # --only luw2,suw — пересобрать часть таблиц. Полный проход по luw2 занимает
    # минуты, и гонять его ради правки в таблице знаков незачем.
    want = list(BUILDERS)
    for i, a in enumerate(sys.argv):
        if a == "--only" and i + 1 < len(sys.argv):
            want = [x.strip() for x in sys.argv[i + 1].split(",") if x.strip()]
    unknown = [w for w in want if w not in BUILDERS]
    if unknown:
        sys.exit("не знаю таких таблиц: " + ", ".join(unknown))
    os.makedirs(OUT, exist_ok=True)
    for w in want:
        fn, d, src = BUILDERS[w]
        fn(os.path.join(d, src), w)
    print("\nПосле пересборки обязательно: python corpus.py")
