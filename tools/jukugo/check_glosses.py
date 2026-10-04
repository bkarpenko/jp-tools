#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_glosses.py — механическая сверка переводов внутри одного разбора компаунда.

ЗАЧЕМ. Разбор цитирует одну и ту же глоссу или цитату в нескольких секциях.
Если перевод при каждом цитировании пишется заново, он расходится, и читатель
видит два разных английских (или русских) у одной китайской строки. На глаз это
не ловится: расхождения стоят в разных концах файла.

КАК. В разборе есть секция «§6. Единицы перевода» — таблица, где у каждой
оригинальной строки ровно один английский и ровно один русский перевод.
Скрипт берёт её за единственный источник правды и проверяет тело разбора:

  [E1] английская строка в теле, которой нет в таблице   -> ОШИБКА
  [E2] пара EN / RU в теле, не совпадающая со строкой таблицы -> ОШИБКА
  [E3] в таблице два ряда с одним оригиналом, но разным переводом -> ОШИБКА
  [E4] в слоте засвидетельствованного значения стоит не словарная
       глосса Г/Я, а ряд С (формулировка разбора) или Ц (цитата) -> ОШИБКА
       Слоты: «старшее значение» в итоговой формуле, строка **EN:**
       под **Толкование:**, звенья блока «Связь значений».
       Там же сверяется оригинал, если он в слоте назван.
       E4 НЕ сверяет перевод с оригиналом: дословность здесь —
       относительно §6, верность самой §6 словарю проверяется глазами.
  [E5] буквальная сумма — не только глоссы знаков: строка **букв. значение:**
       должна состоять из «<знак> *"EN"* / «RU»» через « + », по одной
       на каждый знак компаунда, по порядку, и EN — английский ряда Г/Я
       этого знака в §6. Связки, «make them», толкование — запрещены:
       они идут отдельной строкой после суммы                     -> ОШИБКА
  [E6] круговая глосса: в сумме стоит глосса знака, в оригинале которой
       сам компаунд (в полном или упрощённом написании); либо круговые
       глоссы в §6 есть, а слово «кругов…» в разборе не встречается -> ОШИБКА
  [E7] в блоке «Тип связи» у знака нет строки части речи вида
       «- **<знак> — <часть речи>.** 「пример」 …» — часть речи не
       обоснована управлением в примере                          -> ОШИБКА
  [E8] строка «**связное прочтение…**» в «Итоговой формуле» не помечена
       [ВЫВОД]                                                     -> ОШИБКА
  [W1] русская строка от 5 слов, которой нет в таблице    -> ПРЕДУПРЕЖДЕНИЕ
  [W2] короткая русская строка, начинающаяся как канонический
       перевод, но ему не равная (перефразировка)             -> ПРЕДУПРЕЖДЕНИЕ
  [W4] в §6 есть круговая глосса знака — перечень для проверки,
       что разбор назвал её и не взял в сумму                    -> ПРЕДУПРЕЖДЕНИЕ

Знак ряда Г/Я определяется по помете: в ней назван знак и не назван сам компаунд
(«漢語大詞典, 上 знач. 1-1» — ряд знака, «漢語大詞典 上達 знач. 1» — ряд слова).
Упрощённое написание компаунда берётся из строки шапки
«**Упрощённое написание:** …»; без неё E6 ищет только полное написание.

Разметка знаками в квадратных скобках — "to reach [達] what lies above [上]" —
единственное допустимое отличие от канонической строки: скрипт её снимает
перед сравнением.

ЧЕГО СКРИПТ НЕ ДЕЛАЕТ. Он не судит о качестве перевода. Калька остаётся калькой,
если она одинакова во всём файле. Качество — на правилах шага 10, не здесь.

ЗАПУСК:
    python3 tools/jukugo/check_glosses.py <путь к разбору>.md
Код возврата: 0 — чисто, 1 — есть ошибки.
"""

import re
import sys
import unicodedata

SEC6 = "§6. Единицы перевода"
KANJI_MARK = re.compile(r"\s*\[[㐀-鿿぀-ヿ]\]")
EN_IN_TEXT = re.compile(r'\*"([^"\n]+)"\*')
RU_IN_TEXT = re.compile(r"«([^»\n]+)»")
PAIR_INLINE = re.compile(r'\*"([^"\n]+)"\*\s*/\s*«([^»\n]+)»')
# Звено блока «Связь значений»: **1. Китайское, исходное:** …
CHAIN_LINK = re.compile(r"^\*\*\d+\.[^*]*:\*\*")


def norm(s: str) -> str:
    """Снять разметку знаками, схлопнуть пробелы, нормализовать юникод."""
    s = unicodedata.normalize("NFKC", s)
    s = KANJI_MARK.sub("", s)
    s = s.replace("**", "").replace("*", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_body_and_table(text):
    idx = text.find(SEC6)
    if idx == -1:
        return text, ""
    return text[:idx], text[idx:]


def parse_units(table_text):
    """Ряды вида: | ID | Оригинал | EN | RU | Помета |"""
    units = []
    for line in table_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if set(cells[0]) <= set("-: "):          # разделитель шапки
            continue
        if cells[0].lower() in ("id", "ид"):     # шапка
            continue
        uid, orig, en, ru = cells[0], cells[1], cells[2], cells[3]
        note = cells[4] if len(cells) > 4 else ""
        en_c = norm(en.strip().strip('"'))
        ru_c = norm(ru.strip().strip("«»"))
        if not en_c and not ru_c:
            continue
        units.append({"id": uid, "orig": norm(orig), "en": en_c, "ru": ru_c, "note": note})
    return units


def main(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()

    body, table = split_body_and_table(text)
    if not table:
        print(f"ОШИБКА: в файле нет секции «{SEC6}» — сверять не с чем.")
        return 1

    units = parse_units(table)
    if not units:
        print(f"ОШИБКА: секция «{SEC6}» найдена, но ни одного ряда не разобрано.")
        return 1

    en_ok = {u["en"] for u in units if u["en"]}
    ru_ok = {u["ru"] for u in units if u["ru"]}
    pairs_ok = {(u["en"], u["ru"]) for u in units if u["en"] and u["ru"]}

    errors, warnings = [], []

    # E3 — противоречия внутри самой таблицы
    by_orig = {}
    for u in units:
        if not u["orig"] or u["orig"] == "—":
            continue
        by_orig.setdefault(u["orig"], []).append(u)
    for orig, rows in by_orig.items():
        if len({(r["en"], r["ru"]) for r in rows}) > 1:
            ids = ", ".join(r["id"] for r in rows)
            errors.append(f"[E3] один оригинал, разные переводы — ряды {ids}: {orig[:40]}")

    body_lines = body.splitlines()

    # E4 — в слоте засвидетельствованного значения должна стоять словарная глосса
    #      (ряд Г или Я), а не формулировка разбора (ряд С) и не цитата (ряд Ц):
    #      иначе вывод о знаках попадает в значение целого и формула доказывает
    #      себя сама. Слоты названы по фактической разметке разбора: строка
    #      «старшее значение» итоговой формулы, строка **EN:** под **Толкование:**
    #      (так устроены блоки «Старшее значение» и «Современное значение
    #      в японском» — отдельной строки «современное значение» в разборе нет)
    #      и звенья блока «Связь значений». Буквальная сумма знаков слотом не
    #      является, но ряда С в ней нет и там: её состав проверяет E5.
    dict_rows = [u for u in units if u["id"][:1] in ("Г", "Я") and u["en"]]
    dict_en = {u["en"] for u in dict_rows}
    OLDEST_SLOT = "**старшее значение:**"
    prev = ""
    for n, line in enumerate(body_lines, 1):
        s = line.strip()
        if s.startswith(OLDEST_SLOT):
            head_src, where = s[len(OLDEST_SLOT):], "строке «старшее значение»"
        elif s.startswith("**EN:**") and prev.startswith("**Толкование:**"):
            head_src, where = prev[len("**Толкование:**"):], "толковании словаря"
        elif CHAIN_LINK.match(s):
            head_src, where = CHAIN_LINK.sub("", s, count=1), "звене «Связи значений»"
        else:
            if s:
                prev = s
            continue
        prev = s

        m = EN_IN_TEXT.search(s)
        if not m:
            errors.append(
                f"[E4] стр. {n}: в {where} нет английского — сверить его с §6 нечем"
            )
            continue
        cand = norm(m.group(1))
        if cand not in dict_en:
            ids = ", ".join(sorted(u["id"] for u in units if u["en"] == cand))
            src = f"ряд {ids}" if ids else "строка, которой нет в §6"
            errors.append(
                f"[E4] стр. {n}: в {where} стоит не глосса словаря (Г/Я), "
                f"а {src} — \"{cand[:60]}\""
            )
            continue
        # Оригинал, если он в слоте назван, должен быть оригиналом той же глоссы.
        head = norm(head_src.split('*"', 1)[0]).strip(" —–-")
        if head and head not in {u["orig"] for u in dict_rows if u["en"] == cand}:
            errors.append(
                f"[E4] стр. {n}: в {where} оригинал не совпадает с оригиналом "
                f"этой глоссы в §6 — «{head[:40]}»"
            )

    # E1 — английский в теле, которого нет в таблице
    for n, line in enumerate(body_lines, 1):
        for m in EN_IN_TEXT.finditer(line):
            cand = norm(m.group(1))
            if cand not in en_ok:
                errors.append(f"[E1] стр. {n}: английского нет в §6 — \"{cand}\"")

    # E2 — пара EN / RU на одной строке
    for n, line in enumerate(body_lines, 1):
        for m in PAIR_INLINE.finditer(line):
            pair = (norm(m.group(1)), norm(m.group(2)))
            if pair not in pairs_ok:
                errors.append(
                    f"[E2] стр. {n}: пара EN/RU не совпадает ни с одним рядом §6 — "
                    f"\"{pair[0][:50]}\" / «{pair[1][:50]}»"
                )

    # E2 — блок **EN:** / **RU:** соседними строками
    for n in range(len(body_lines) - 1):
        a, b = body_lines[n].strip(), body_lines[n + 1].strip()
        if a.startswith("**EN:**") and b.startswith("**RU:**"):
            ma = EN_IN_TEXT.search(a)
            mb = RU_IN_TEXT.search(b)
            if ma and mb:
                pair = (norm(ma.group(1)), norm(mb.group(1)))
                if pair not in pairs_ok:
                    errors.append(
                        f"[E2] стр. {n+1}–{n+2}: пара EN/RU не совпадает ни с одним рядом §6 — "
                        f"\"{pair[0][:50]}\" / «{pair[1][:50]}»"
                    )

    # ---------- E5 / E6 / E7 / E8 / W4 ----------
    title = re.match(r"#\s*(\S+)", text)
    compound = title.group(1) if title else ""
    simp_m = re.search(r"\*\*Упрощённое написание:\*\*\s*(\S+)", text)
    simplified = simp_m.group(1) if simp_m else ""
    if not simplified:
        try:
            import opencc  # необязательно
            simplified = opencc.OpenCC("t2s").convert(compound)
        except Exception:
            simplified = ""
    forms = {f for f in (compound, simplified) if f}
    chars = list(dict.fromkeys(compound))

    def char_row(u, ch):
        """Ряд глоссы знака ch: знак назван в помете, а компаунд — нет."""
        return ch in u["note"] and not any(f in u["note"] for f in forms)

    def block(name):
        """Строки тела от заголовка «## name…» до следующего «## » или «---»."""
        out, on = [], False
        for n, line in enumerate(body_lines, 1):
            st = line.strip()
            if st.startswith("## "):
                if on:
                    break
                on = st[3:].startswith(name)
                continue
            if on and st == "---":
                break
            if on:
                out.append((n, st))
        return out

    # W4 / E6 — круговые ряды Г: глосса знака, в оригинале которой стоит сам компаунд.
    circ_rows = [u for u in units if u["id"][:1] == "Г"
                 and any(f in u["orig"] for f in forms)
                 and any(char_row(u, ch) for ch in chars)]
    circ_en = {u["en"] for u in circ_rows}
    for u in circ_rows:
        warnings.append(f"[W4] круговая глосса знака — ряд {u['id']}: {u['orig'][:40]}")
    if circ_rows and "кругов" not in body:
        errors.append("[E6] в §6 есть круговые глоссы знаков, но разбор их нигде не называет "
                      "(слово «кругов…» не встречается)")

    # E5 — буквальная сумма = только глоссы знаков: «<знак> *"EN"* / «RU»» через « + »,
    #      по одной на каждый знак, в порядке знаков; EN — английский ряда Г/Я этого знака.
    #      Никаких связок и толкования: они идут отдельной строкой после суммы (E8).
    PIECE = re.compile(r'^(\S)\s+\*"([^"]+)"\*\s*/\s*«([^»]+)»$')
    formula = block("Итоговая формула")
    bukv = [(n, st) for n, st in formula if st.startswith("**букв. значение:**")]
    if not bukv:
        errors.append("[E5] в «Итоговой формуле» нет строки **букв. значение:**")
    else:
        bn, bst = bukv[0]
        pieces = [p.strip() for p in bst[len("**букв. значение:**"):].split(" + ")]
        got = []
        for p in pieces:
            m = PIECE.match(p)
            if not m:
                errors.append(f"[E5] стр. {bn}: в буквальной сумме не глосса знака, а «{p[:50]}» — "
                              "сумма пишется только как «<знак> *\"EN\"* / «RU»» через « + », "
                              "толкование — отдельной строкой после неё")
                continue
            ch, en = m.group(1), norm(m.group(2))
            got.append(ch)
            rows = [u for u in units if u["id"][:1] in ("Г", "Я") and u["en"] == en
                    and char_row(u, ch)]
            if not rows:
                errors.append(f"[E5] стр. {bn}: у {ch} в сумме «{en[:40]}» — это не английский "
                              f"ни одного ряда Г/Я этого знака в §6")
            elif en in circ_en:
                errors.append(f"[E6] стр. {bn}: у {ch} в сумме круговая глосса — «{en[:40]}»; "
                              "в её оригинале сам разбираемый компаунд")
        if got and got != chars:
            errors.append(f"[E5] стр. {bn}: в сумме знаки {''.join(got)}, а в компаунде "
                          f"{''.join(chars)} — по одной глоссе на каждый знак, по порядку")
        # E8 — толкование после суммы помечено как вывод
        for n, st in formula:
            if st.startswith("**связное прочтение") and "[ВЫВОД]" not in st:
                errors.append(f"[E8] стр. {n}: строка связного прочтения не помечена [ВЫВОД]")

    # E7 — строка части речи у каждого знака в блоке «Тип связи»
    tblock = block("Тип связи")
    for ch in chars:
        pat = re.compile(r"^-\s*\*\*" + re.escape(ch) + r"\s*—[^*]*\*\*.*「")
        if not any(pat.match(st) for n, st in tblock):
            errors.append(f"[E7] в блоке «Тип связи» нет строки части речи для {ch}: "
                          f"«- **{ch} — <часть речи>.** 「пример」 …» — часть речи по управлению "
                          "в датированном примере, а не по английскому переводу")

    def head(s):
        w = s.split()
        return re.sub(r"[^\w-]+$", "", w[0]).lower() if w else ""

    ru_heads = {head(r) for r in ru_ok if r}

    # W1 — длинный русский вне таблицы
    # W2 — короткая русская строка, начинающаяся как канонический перевод,
    #      но ему не равная: типичная незамеченная перефразировка
    for n, line in enumerate(body_lines, 1):
        for m in RU_IN_TEXT.finditer(line):
            cand = norm(m.group(1))
            if cand in ru_ok:
                continue
            words = cand.split()
            if len(words) >= 5:
                warnings.append(f"[W1] стр. {n}: длинная русская строка вне §6 — «{cand[:60]}»")
            elif len(words) >= 2 and head(cand) in ru_heads:
                warnings.append(
                    f"[W2] стр. {n}: похоже на перефразировку канонического перевода — «{cand[:60]}»"
                )

    print(f"Единиц перевода в §6: {len(units)}")
    print(f"Ошибок: {len(errors)}   Предупреждений: {len(warnings)}")
    if errors:
        print("\n--- ОШИБКИ ---")
        for e in errors:
            print(e)
    if warnings:
        print("\n--- ПРЕДУПРЕЖДЕНИЯ (смотреть глазами) ---")
        for w in warnings:
            print(w)
    if not errors and not warnings:
        print("\nЧисто.")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check_glosses.py <разбор>.md")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
