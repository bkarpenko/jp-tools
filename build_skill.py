#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка скиллов из репозитория в zip для загрузки в Claude.

    python build_skill.py              собрать все инструменты
    python build_skill.py freq         собрать один (по имени каталога или скилла)
    python build_skill.py --xz         данные перепаковать в .xz: втрое легче,
                                       распаковка медленнее (запасной вариант,
                                       если загрузка не примет размер)

Сборщик не знает ни одного инструмента по имени. Он обходит tools/*/skill.json
и кладёт в архив то, что там перечислено. Добавить четвёртый инструмент — это
положить каталог с SKILL.md и манифестом, ничего здесь не трогая.

Манифест (tools/<каталог>/skill.json):

    {
      "name":   "jp-freq",                        имя скилла и корня в архиве
      "files":  ["freq.py", "references/"],       из каталога инструмента;
                                                  имя с / — каталог целиком
      "shared": ["corpus.py"],                    из shared/, ложится в корень
      "data":   ["kanji", "suw", "luw2"]          из shared/data/, ложится в data/
    }

SKILL.md берётся из корня каталога инструмента всегда и в манифесте не
указывается: скилла без него не бывает.

Собранный пакет самодостаточен и в сеть не ходит: всё, что ему нужно, лежит
рядом с SKILL.md. Установленная копия — артефакт сборки. Править её на месте
нельзя: правка, которой нет в репозитории, теряется при следующей сборке.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "tools")
SHARED = os.path.join(HERE, "shared")
DATA = os.path.join(SHARED, "data")
DIST = os.path.join(HERE, "dist")


def die(msg):
    sys.exit("сборка не удалась: " + msg)


def manifests() -> dict:
    """{каталог инструмента: манифест} — по всем tools/*/skill.json."""
    found = {}
    if not os.path.isdir(TOOLS):
        die("нет каталога tools/")
    for d in sorted(os.listdir(TOOLS)):
        path = os.path.join(TOOLS, d, "skill.json")
        if not os.path.isfile(path):
            continue
        try:
            m = json.load(io.open(path, encoding="utf-8"))
        except ValueError as e:
            die(f"tools/{d}/skill.json не читается как JSON: {e}")
        if not m.get("name"):
            die(f"tools/{d}/skill.json без поля name")
        found[d] = m
    if not found:
        die("не нашёл ни одного tools/*/skill.json")
    return found


def skill_name(md_path: str) -> str | None:
    """Имя из фронтматтера SKILL.md. Нужно, чтобы поймать расхождение
    с манифестом: переименовал скилл в одном месте — узнаешь при сборке,
    а не когда Claude не найдёт его по имени."""
    head = io.open(md_path, encoding="utf-8").read(4096)
    m = re.match(r"---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return None
    m = re.search(r"^name:\s*(.+?)\s*$", m.group(1), re.M)
    return m.group(1) if m else None


def read_table(path: str) -> bytes:
    """Содержимое таблицы распакованным."""
    if path.endswith(".xz"):
        import lzma
        return lzma.open(path, "rb").read()
    if path.endswith(".gz"):
        import gzip
        return gzip.open(path, "rb").read()
    return io.open(path, "rb").read()


def table_path(stem: str) -> str:
    for ext in (".tsv", ".tsv.gz", ".tsv.xz"):
        p = os.path.join(DATA, stem + ext)
        if os.path.exists(p):
            return p
    die(f"нет таблицы {stem} в shared/data/")


def walk(root: str):
    """Пары (абсолютный путь, путь относительно root) для всех файлов внутри."""
    for base, _, names in os.walk(root):
        for n in sorted(names):
            p = os.path.join(base, n)
            yield p, os.path.relpath(p, root)


def add(z: zipfile.ZipFile, src: str, arc: str, seen: dict) -> int:
    """Кладёт файл в архив, ловя два имени на одно место."""
    if arc in seen:
        die(f"два файла претендуют на {arc}: {seen[arc]} и {src}")
    seen[arc] = src
    z.write(src, arc)
    return os.path.getsize(src)


def build(tool_dir: str, m: dict, as_xz: bool) -> str:
    name = m["name"]
    src_dir = os.path.join(TOOLS, tool_dir)
    md = os.path.join(src_dir, "SKILL.md")
    if not os.path.isfile(md):
        die(f"нет tools/{tool_dir}/SKILL.md")
    declared = skill_name(md)
    if declared and declared != name:
        die(f"tools/{tool_dir}: во фронтматтере SKILL.md имя «{declared}», "
            f"а в манифесте «{name}» — расходятся")

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, name + "-skill.zip")
    seen, total = {}, 0

    # без сжатия: и .gz, и .xz уже сжаты, второй проход только тратит время
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        total += add(z, md, name + "/SKILL.md", seen)

        for item in m.get("files", []):
            p = os.path.join(src_dir, item.rstrip("/"))
            if item.endswith("/") or os.path.isdir(p):
                if not os.path.isdir(p):
                    die(f"tools/{tool_dir}: нет каталога {item}")
                for f, rel in walk(p):
                    total += add(z, f, f"{name}/{item.rstrip('/')}/{rel}", seen)
            else:
                if not os.path.isfile(p):
                    die(f"tools/{tool_dir}: нет файла {item}")
                total += add(z, p, f"{name}/{item}", seen)

        for item in m.get("shared", []):
            p = os.path.join(SHARED, item)
            if not os.path.isfile(p):
                die(f"tools/{tool_dir}: нет shared/{item}")
            total += add(z, p, f"{name}/{item}", seen)

        for stem in m.get("data", []):
            src = table_path(stem)
            if as_xz and not src.endswith(".xz"):
                import lzma
                blob = lzma.compress(read_table(src), preset=6)
                arc = f"{name}/data/{stem}.tsv.xz"
            else:
                blob = io.open(src, "rb").read()
                arc = f"{name}/data/{os.path.basename(src)}"
            if arc in seen:
                die(f"два файла претендуют на {arc}")
            seen[arc] = src
            z.writestr(arc, blob)
            total += len(blob)

    size = os.path.getsize(out)
    print(f"  {name:<20} {len(seen):>3} файлов, содержимое {total/1e6:>6.1f} МБ, "
          f"архив {size/1e6:>6.1f} МБ")
    return out


def main():
    args = [a for a in sys.argv[1:]]
    as_xz = "--xz" in args
    wanted = [a for a in args if not a.startswith("-")]

    found = manifests()
    if wanted:
        pick = {}
        for w in wanted:
            hit = [d for d, m in found.items() if w in (d, m["name"])]
            if not hit:
                die(f"не знаю инструмента «{w}». Есть: "
                    + ", ".join(f"{d} ({m['name']})" for d, m in found.items()))
            pick[hit[0]] = found[hit[0]]
        found = pick

    print("сборка в dist/:")
    outs = [build(d, m, as_xz) for d, m in found.items()]
    print("\n" + "\n".join(outs))
    if not as_xz and any(os.path.getsize(o) > 20e6 for o in outs):
        print("если загрузка не примет размер — пересобрать с --xz")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
