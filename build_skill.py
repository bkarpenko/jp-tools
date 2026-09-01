#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка скилла jp-freq в zip для загрузки в Claude.

Скилл — это тот же инструмент, но с данными внутри: он должен работать
в обычном чате, где компьютер не подключён и папки проекта нет.

    python build_skill.py            собрать dist/jp-freq-skill.zip (данные .gz, ~23 МБ)
    python build_skill.py --xz       перепаковать данные в .xz (~16 МБ, распаковка медленнее)

Источник правды — репозиторий: skill/SKILL.md, freq.py, data/. Установленная
копия скилла всегда пересобирается отсюда, править её на месте нельзя: правка,
которой нет в репозитории, теряется при следующей сборке.
"""
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "jp-freq"
TABLES = ("kanji", "luw2", "suw", "writing")


def data_path(stem):
    for ext in (".tsv", ".tsv.gz", ".tsv.xz"):
        p = os.path.join(HERE, "data", stem + ext)
        if os.path.exists(p):
            return p
    sys.exit("нет таблицы " + stem + " в data/ — собирать нечего")


def read_table(path):
    """Возвращает содержимое таблицы распакованным."""
    if path.endswith(".xz"):
        import lzma
        return lzma.open(path, "rb").read()
    if path.endswith(".gz"):
        import gzip
        return gzip.open(path, "rb").read()
    return io.open(path, "rb").read()


def main():
    as_xz = "--xz" in sys.argv[1:]
    skill_md = os.path.join(HERE, "skill", "SKILL.md")
    if not os.path.exists(skill_md):
        sys.exit("нет skill/SKILL.md")

    out_dir = os.path.join(HERE, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, NAME + "-skill.zip")

    # zip без сжатия: и .gz, и .xz уже сжаты, второй проход только тратит время
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.write(skill_md, NAME + "/SKILL.md")
        z.write(os.path.join(HERE, "freq.py"), NAME + "/freq.py")
        total = 0
        for stem in TABLES:
            src = data_path(stem)
            if as_xz and not src.endswith(".xz"):
                import lzma
                blob = lzma.compress(read_table(src), preset=6)
                arc = NAME + "/data/" + stem + ".tsv.xz"
            else:
                blob = io.open(src, "rb").read()
                arc = NAME + "/data/" + os.path.basename(src)
            z.writestr(arc, blob)
            total += len(blob)
            print("  %-22s %8.1f МБ" % (os.path.basename(arc), len(blob) / 1e6))

    size = os.path.getsize(out)
    print("\n%s\nвсего данных %.1f МБ, архив %.1f МБ" % (out, total / 1e6, size / 1e6))
    if not as_xz:
        print("если загрузка не примет размер — пересобрать с --xz (около 16 МБ)")


if __name__ == "__main__":
    main()
