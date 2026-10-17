# -*- coding: utf-8 -*-
"""
Тест предупреждений W7–W9 сверщика check_glosses.py.

Синтетический разбор нарочно нарушает все три правила: «окончательно» в теле,
голое *it* в связном прочтении, ветка A без разделов «Матрица прочтений»
и «Тексты употребления». Контрольный разбор — тот же, но исправленный: в нём
W7–W9 молчат. Образцы examples/ должны давать ноль ошибок (W9 на них ожидаем:
они написаны до шагов М1–М2).

ЗАПУСК:
    python3 -m unittest discover tools/jukugo/tests
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, TOOL)

import check_glosses  # noqa: E402

BAD = """# 甲乙

Ветка A. Конкурент отсечён окончательно.

## Итоговая формула

**связное прочтение [ВЫВОД]:** *"to require it of him"* / «требовать этого от него» — на чём держится: роль.

# §6. Единицы перевода

| ID | Оригинал | RU | EN | Помета |
|---|---|---|---|---|
| С1 | — | «требовать этого от него» | "to require it of him" | формулировка разбора |
"""

GOOD = """# 甲乙

Ветка A. Конкурент ослаблен: довод назван в §2.

## §2. Связные прочтения и отсечение

### Матрица прочтений

### Тексты употребления

## Итоговая формула

**связное прочтение [ВЫВОД]:** *"to require something of someone"* / «требовать чего-л. от кого-л.» — на чём держится: роль.

# §6. Единицы перевода

| ID | Оригинал | RU | EN | Помета |
|---|---|---|---|---|
| С1 | — | «требовать чего-л. от кого-л.» | "to require something of someone" | формулировка разбора |
"""


def run(text):
    """Прогнать сверщик по тексту разбора; вернуть (код возврата, вывод)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8",
                                     delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return run_path(path)
    finally:
        os.unlink(path)


def run_path(path):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check_glosses.main(path)
    return code, out.getvalue()


class NewWarnings(unittest.TestCase):

    def test_bad_fires_w7_w8_w9(self):
        _, out = run(BAD)
        for w in ("[W7]", "[W8]", "[W9]"):
            self.assertEqual(out.count(w), 1, f"{w} должен сработать ровно раз:\n{out}")

    def test_good_is_silent(self):
        _, out = run(GOOD)
        for w in ("[W7]", "[W8]", "[W9]"):
            self.assertNotIn(w, out, out)

    def test_examples_have_no_errors(self):
        ex = os.path.join(TOOL, "examples")
        for name in ("上達.md", "小遣い.md"):
            code, out = run_path(os.path.join(ex, name))
            self.assertEqual(code, 0, f"{name}:\n{out}")
            self.assertIn("Ошибок: 0", out, name)


if __name__ == "__main__":
    unittest.main()
