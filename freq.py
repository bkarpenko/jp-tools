#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jp-freq — частотная справка по японскому кандзи или слову из корпуса BCCWJ.

    python freq.py 浸              один знак -> справка по кандзи
    python freq.py 浸かる           слово     -> справка по слову
    python freq.py --html 浸かる    то же самое страницей (полосы вместо колонок)
    python freq.py --check         проверка целостности данных

Зависимостей нет: только стандартная библиотека.
Данные лежат в data/, устройство — в docs/data.md, шкалы — в docs/scale.md.

Устройство модуля: сбор данных (collect_*) отделён от вывода (render_text_*,
render_html). Оба режима читают один и тот же словарь, поэтому расходиться
числами они не могут.
"""

from __future__ import annotations

import gzip
import html as _h
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

# Где искать таблицы. Порядок важен: сначала то, что положено осознанно,
# потом типовые места, куда файлы кладёт заливка в песочницу.
SEARCH_DIRS = [d for d in (
    os.environ.get("JP_FREQ_DATA"),
    os.path.join(HERE, "data"), HERE,
    os.path.join(os.getcwd(), "data"), os.getcwd(),
    "/mnt/user-data/uploads", "/mnt/session/uploads", "/mnt/data",
    os.path.expanduser("~"),
) if d and os.path.isdir(d)]

# ------------------------------------------------------------------ шкалы
# Пороги вердикта заданы кумулятивным покрытием корпуса, а не на глаз (docs/scale.md).
# Формулировки полос отвечают на вопрос «что это значит», а не «какой порог
# сработал»: сколько знаков или слов в полосе и сколько текста они закрывают.
# Числа посчитаны по data/ (метод — в docs/scale.md) и при пересборке корпуса
# требуют пересчёта вместе с ней.
# Полосы заданы рангами, а обоснованы покрытием. Последняя граница не круглое
# число, а конец рабочего списка: он вычисляется из данных (см. CORE_COVERAGE),
# поэтому достраивается к списку уже в collect_kanji.
KANJI_BANDS = [
    (500,   "ЯДРО",            "первые 500 знаков — 75,7 % всех кандзи в тексте"),
    (1000,  "ОЧЕНЬ ЧАСТЫЙ",    "до 1000-го ранга — 91,2 %"),
    (1500,  "ОБЫЧНЫЙ",         "до 1500-го ранга — 96,8 %"),
    (2000,  "НА КРАЮ ОБИХОДА", "до 2000-го ранга — 98,8 %"),
]
KANJI_LAST = ("РЕДКИЙ", "последняя четверть рабочего списка")
KANJI_TAIL = ("ОЧЕНЬ РЕДКИЙ",
              "за рабочим списком: имена собственные, цитаты, разовые написания")

# Полосы идут десятичными шагами, потому что так устроено само распределение:
# каждая следующая означает, что текста до встречи нужно прочитать вдесятеро
# больше. Формулировка даётся именно в этом виде — «раз на столько-то слов».
WORD_BANDS = [
    (100.0, "ОЧЕНЬ ЧАСТОЕ", "чаще раза на 10 тысяч слов"),
    (10.0,  "ЧАСТОЕ",       "раз на 10–100 тысяч слов"),
    (1.0,   "ОБЫЧНОЕ",      "раз на 100 тысяч — миллион слов"),
    (0.1,   "РЕДКОЕ",       "раз на 1–10 миллионов слов"),
]
WORD_TAIL = ("НА ГРАНИ", "реже раза на 10 миллионов слов")
# Концы шкалы слова в pmw. Домен ровно пять декад, поэтому границы полос
# (100, 10, 1, 0,1) ложатся на 20, 40, 60 и 80 % ширины сами собой.
WORD_SCALE_HI, WORD_SCALE_LO = 1000.0, 0.01

KANJI_TOTAL = 6940          # знаков в таблице знаков BCCWJ
LUW2_TOTAL = 841976         # типов в luw2 (слов с частотой 1 в нём нет)
SUW_TOTAL = 185136          # типов в suw
KANJI_TOKENS = 59255969     # всего вхождений кандзи в корпусе (знаменатель кум%)
KANJI_CHARS = 195322813     # всего символов в корпусе (знаменатель pmw в kanji.tsv)
LUW_TOKENS = 83308386       # всего токенов LUW (знаменатель pmw в luw2)
# Знаменателей три, и они разные. pmw в kanji.tsv считается от ВСЕХ символов
# корпуса, а не от кандзи: 1918 / 9,8196 * 1e6 = 195 322 813, и то же число
# выходит для 人, 一, 日, 閲. Кандзи среди этих символов только 30,3 %.
# Сумма freq в luw2.tsv.gz (81 715 641) — это корпус БЕЗ 1 592 745 хапаксов,
# поэтому доли покрытия считаются от LUW_TOKENS, иначе они завышены на 1,4 п.п.

# Коды жанровых подкорпусов BCCWJ. Без расшифровки строка «OB,LB,PB» не значит
# ничего, а значит она немало: у неё видно, в какой прозе слово живёт.
REGISTERS = {
    "PB": "книги", "LB": "библиотечные книги", "OB": "бестселлеры",
    "PM": "журналы", "PN": "газеты", "OW": "официальные документы",
    "OT": "учебники", "OP": "брошюры администраций", "OL": "законы",
    "OC": "Yahoo! Chiebukuro (вопросы-ответы)", "OY": "Yahoo! Blog",
    "OV": "стихи", "OM": "стенограммы парламента",
}
BOOKISH = {"PB", "LB", "OB"}

# Жанры сведены в семьи: тринадцать кодов подряд не читаются, а «книжное /
# периодика / официальное» отвечает на вопрос, где слово живёт.
GENRE_GROUPS = [
    ("книги и проза", ["PB", "LB", "OB"]),
    ("периодика",     ["PM", "PN"]),
    ("официальное",   ["OW", "OL", "OP", "OM"]),
    ("учебное",       ["OT"]),
    ("сеть",          ["OC", "OY"]),
    ("стихи",         ["OV"]),
]
GROUP_OF = {c: g for g, cs in GENRE_GROUPS for c in cs}


def parse_regs(cell: str) -> dict:
    """'PB82.5,LB116,OB206' -> {'PB': 82.5, 'LB': 116.0, 'OB': 206.0}.

    Колонка появилась при пересборке 2026-08-31: до неё в data/ лежали только
    охват и тройка лидеров, и профиль по жанрам было не из чего строить.
    """
    out = {}
    for item in cell.split(","):
        item = item.strip()
        if len(item) < 3:
            continue
        code, val = item[:2], item[2:]
        if code not in REGISTERS:
            continue
        try:
            out[code] = float(val)
        except ValueError:
            continue
    return out

# Полный список знаков корпуса как знаменатель льстит: его хвост — имена
# собственные, китайские цитаты и опечатки, встретившиеся по разу. Рабочим
# списком считаются знаки, накрывающие CORE_COVERAGE вхождений; граница
# берётся из данных на лету, поэтому при пересборке корпуса не устаревает.
CORE_COVERAGE = 99.5

def scale_marks(rank: int, total: int) -> list:
    """Опорные ранги для таблицы соседей: около десяти строк, не больше.

    Фиксированный список (1, 100, 1000, 3000…) оставлял дыру ровно там, где стоит
    искомое. Первая попытка чинить это линейной лесенкой дала обратный перекос —
    пятнадцать строк, из которых половина одинаковые. Здесь опорами служат декады
    (их глаз читает как порядки) плюс одна середина между последней декадой
    и рангом, а сверху — редкая геометрия.
    """
    import math

    def nice(v: float) -> int:
        mag = 10 ** int(math.floor(math.log10(v)))
        return int(round(v / mag) * mag)

    marks = {1, rank - 1, rank, rank + 1}
    decades = []
    d = 10
    while d < rank:
        decades.append(d)
        d *= 10
    decades = decades[-3:]                      # трёх порядков снизу хватает
    marks.update(decades)
    if rank > 20:                               # середина последнего пролёта
        mid = nice(rank / 2)
        if not decades or mid > decades[-1] * 1.5:
            marks.add(mid)
    top = 0
    for mult in (3, 10, 50):                    # что идёт после искомого
        v = nice(rank * mult)
        if v < total:
            marks.add(v)
            top = max(top, v)
    if total > top * 1.5:                       # дальний конец списка
        marks.add(total)
    return sorted(x for x in marks if 1 <= x <= total)


def is_kanji(ch: str) -> bool:
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF


def is_hira(ch: str) -> bool:
    return 0x3041 <= ord(ch) <= 0x3096


def is_kata(ch: str) -> bool:
    o = ord(ch)
    return 0x30A1 <= o <= 0x30FA or 0x31F0 <= o <= 0x31FF


# Знаки долготы и повтора не принадлежат ни одной из азбук: они встают и после
# хираганы, и после катаканы. Если считать их буквами, "だーめ" уедет в катакану
# из-за одного U+30FC. Поэтому при выборе азбуки они не голосуют.
NEUTRAL = set("\u30fc\u301c\uff5e\u30fb\u309d\u309e\u30fd\u30fe"
              "\u309b\u309c\u3099\u309a\u3005")


def where(name: str) -> str:
    """Находит таблицу. Заливка в песочницу может разложить файлы плоско
    или в служебный каталог загрузок, поэтому путь не один."""
    for d in SEARCH_DIRS:
        for ext in (".tsv", ".tsv.gz", ".tsv.xz"):
            p = os.path.join(d, name + ext)
            if os.path.exists(p):
                return p
    sys.exit(f"не нашёл таблицу {name}.tsv[.gz|.xz]. Искал в:\n  "
             + "\n  ".join(SEARCH_DIRS)
             + "\nПоложи файлы data/ рядом с freq.py или задай JP_FREQ_DATA.")


def rows(name: str):
    path = where(name)
    # .xz — запасной формат для сборки скилла: те же данные на четверть легче,
    # но распаковка медленнее, поэтому в репозитории лежит .gz
    if path.endswith(".xz"):
        import lzma
        f = lzma.open(path, "rt", encoding="utf-8")
    elif path.endswith(".gz"):
        f = gzip.open(path, "rt", encoding="utf-8")
    else:
        f = open(path, encoding="utf-8")
    with f:
        f.readline()
        for line in f:
            yield line.rstrip("\n").split("\t")


def width(s: str) -> int:
    """Ширина строки в знакоместах: CJK занимает два."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def plural(n, one, few, many):
    """знак / знака / знаков — по русским правилам согласования."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def num(x, digits=2):
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def once_in(pmw: float, unit: str) -> str:
    """9,82 pmw -> 'раз на 102 тыс. символов'. Округление до трёх значащих."""
    if pmw <= 0:
        return "—"
    n = 1_000_000.0 / pmw
    if n >= 1_000_000:
        return "раз на " + num(n / 1_000_000, 1) + " млн " + unit
    if n >= 100_000:
        return "раз на " + num(round(n / 1_000) * 1_000, 0) + " " + unit
    if n >= 1_000:
        return "раз на " + num(round(n / 100) * 100, 0) + " " + unit
    return "раз на " + num(n, 0) + " " + unit


def per_words(pmw: float) -> str:
    """Порог pmw -> сколько единиц приходится на одну встречу: 100 -> «10 тыс.».
    Короткая форма для засечек на шкале, где длинное «раз на …» не помещается.
    У слова пороги ровные (декады), у знака ранги дают что попало — поэтому
    ниже 10 тысяч даётся десятая доля: 6 224 -> «6,2 тыс.»."""
    n = 1_000_000.0 / pmw
    if n >= 10_000_000:
        return num(n / 1_000_000, 0) + " млн"
    if n >= 1_000_000:
        return (num(n / 1_000_000, 0) if abs(n - round(n / 1_000_000) * 1_000_000) < 1
                else num(n / 1_000_000, 1)) + " млн"
    if n >= 10_000:
        return num(n / 1_000, 0) + " тыс."
    if n >= 1_000:
        return (num(n, 0) if abs(n - round(n / 1_000) * 1_000) < 1
                else num(n / 1_000, 1) + " тыс.")
    return num(n, 0)


def verdict(value, bands, tail, ascending):
    for i, (limit, label, note) in enumerate(bands):
        if (value <= limit) if ascending else (value >= limit):
            return i, label, note
    return len(bands), tail[0], tail[1]


KINDS = ("кандзи", "хирагана", "катакана", "прочее")


def form_kind(form: str) -> str:
    """Каким письмом записана форма.

    Кандзи перевешивает всё: вопрос справки — попадётся ли знак на глаза,
    и "浸かる" знак показывает, сколько бы каны рядом ни стояло. Если кандзи
    нет, азбука выбирается по большинству букв, а не по одному вхождению:
    "Ｔシャツ" — это катакана с латинской буквой, а не латиница.
    """
    if any(is_kanji(c) for c in form):
        return "кандзи"
    h = k = o = 0
    for c in form:
        if c in NEUTRAL:
            continue
        if is_hira(c):
            h += 1
        elif is_kata(c):
            k += 1
        elif not c.isspace():
            o += 1
    if o and o >= h and o >= k:
        return "прочее"
    if k and k >= h:
        return "катакана"
    if h:
        return "хирагана"
    return "прочее"


def kanji_core(form: str) -> str:
    """Иероглифическая основа формы: '駄目ぇ' -> '駄目', '玉子' -> '玉子'."""
    return "".join(c for c in form if is_kanji(c))


def script_split(forms: str):
    """'つかる(785),浸かる(291)' -> ({вид: сумма}, [(форма, n, вид)])."""
    tot = {k: 0 for k in KINDS}
    parts = []
    for item in forms.split(","):
        item = item.strip()
        if "(" not in item or not item.endswith(")"):
            continue
        form, tail = item.rsplit("(", 1)
        try:
            n = int(tail[:-1])
        except ValueError:
            continue
        kind = form_kind(form)
        tot[kind] += n
        parts.append((form, n, kind))
    return tot, parts


def find_lemma(query: str):
    """Ищет лемму, если запрос дан реальным написанием: つかる -> 浸かる."""
    hits = []
    for s in rows("writing"):
        forms = [p.rsplit("(", 1)[0].strip() for p in s[6].split(",")]
        if query in forms:
            hits.append((int(s[4]), s[1]))
    hits.sort(reverse=True)
    return hits


# ============================================================ сбор данных
def collect_kanji(ch: str) -> dict:
    table = list(rows("kanji"))
    pos = next((i for i, r in enumerate(table) if r[1] == ch), None)
    if pos is None:
        return {"kind": "kanji", "ch": ch, "found": False}

    r = table[pos]
    rank, freq, pmw, cum, forms_raw = int(r[0]), int(r[2]), float(r[3]), float(r[4]), r[5]
    core_rank = next((int(x[0]) for x in table if float(x[4]) >= CORE_COVERAGE),
                     len(table))
    bands = KANJI_BANDS + [(core_rank, KANJI_LAST[0], KANJI_LAST[1])]
    band, label, note = verdict(rank, bands, KANJI_TAIL, ascending=True)

    # Частота на границах полос: полосы заданы рангами, но ранг сам по себе не
    # говорит, как часто знак попадается. Засечки на шкале дают оба числа.
    edges = {1, len(table), core_rank} | {b[0] for b in KANJI_BANDS}
    pmw_at = {e: float(table[e - 1][3]) for e in edges if 1 <= e <= len(table)}

    marks = sorted(set(scale_marks(rank, len(table))) | {core_rank})
    scale = [{"rank": m, "ch": table[m - 1][1], "pmw": float(table[m - 1][3]),
              "cum": float(table[m - 1][4]), "target": m == rank}
             for m in marks if 1 <= m <= len(table)]

    forms, shown = [], 0
    for item in forms_raw.split("/"):
        if "(" not in item:
            continue
        w, tail = item.rsplit("(", 1)
        try:
            n = int(tail.rstrip(")"))
        except ValueError:
            continue
        shown += n
        forms.append({"form": w, "n": n, "share": 100.0 * n / freq})

    own, nest = [], []
    for s in rows("luw2"):
        if ch in s[2]:
            (own if s[2] == ch else nest).append(s)
    suw_own = [s for s in rows("suw") if s[2] == ch]

    allw = sorted(own + nest, key=lambda s: -float(s[6]))
    mass = sum(float(s[6]) for s in allw) or 1.0
    nest_words = [{"word": s[2], "pmw": float(s[6]), "share": 100.0 * float(s[6]) / mass,
                   "reg": len(parse_regs(s[7])), "pos": s[3]} for s in allw]

    standalone = []
    for base, rs, total in (("LUW2", own, LUW2_TOTAL), ("SUW", suw_own, SUW_TOTAL)):
        for s in rs:
            standalone.append({"base": base, "pos": s[3], "pmw": float(s[6]),
                               "rank": int(s[0]), "total": total})

    return {
        "kind": "kanji", "found": True, "ch": ch,
        "rank": rank, "freq": freq, "pmw": pmw, "cum": cum,
        "band": band, "label": label, "note": note,
        "core_rank": core_rank, "core_cov": CORE_COVERAGE,
        "tail_n": len(table) - core_rank, "tail_share": 100.0 - CORE_COVERAGE,
        "total": len(table), "tokens": KANJI_TOKENS,
        "scale": scale, "pmw_at": pmw_at, "forms": forms,
        "forms_cover": 100.0 * shown / freq,
        "standalone": standalone,
        "nest": nest_words, "nest_mass": mass,
    }


def collect_word(word: str) -> dict:
    # первый проход по luw2: сама лемма и все единицы, куда она входит
    luw, inner = [], []
    for s in rows("luw2"):
        if s[2] == word:
            luw.append(s)
        elif word in s[2]:
            inner.append(s)
    suw = [s for s in rows("suw") if s[2] == word]

    if not luw and not suw:
        return {"kind": "word", "word": word, "found": False,
                "hits": [{"lemma": lemma, "n": n} for n, lemma in find_lemma(word)[:5]]}

    # второй проход набирает шкалу рангов, накопленное покрытие и омонимы
    # по чтению; 842 тысячи строк в память не кладём
    readings = {s[1] for s in (luw or suw)}
    r0 = int(min(luw, key=lambda s: int(s[0]))[0]) if luw else None
    # Опорные точки выбираются по РАНГУ, а не по номеру строки: ранги в luw2
    # повторяются (на 4663-м стоят шесть слов), и отсчёт по строкам давал
    # «ранг 9988» там, где задумано 10 000. Соседи берутся по факту — строка
    # до и строка после искомого, — иначе при совпадении рангов искомое
    # вытеснялось однорангниками и в таблицу не попадало вовсе.
    marks = sorted(set(scale_marks(r0, LUW2_TOTAL)) - {r0 - 1, r0 + 1}) if r0 \
        else [1, 100, 1000, 10000]
    scale_rows, cum_at, same, run = {}, {}, [], 0
    pend = list(marks)
    prev = grab_next = None
    # Ранг в luw2 делится: одинаковая частота — одинаковый ранг (на 4663-м
    # стоят шесть слов). Считаем, сколько слов делит ранг искомого, чтобы
    # таблица шкалы не выдавала три строки с одним числом молча.
    tied = 0
    for i, s in enumerate(rows("luw2"), 1):
        run += int(s[5])
        r = int(s[0])
        if r == r0:
            tied += 1
        while pend and r >= pend[0]:
            pend.pop(0)
            if i not in scale_rows:
                scale_rows[i], cum_at[i] = s, run
        if grab_next and i not in scale_rows:
            scale_rows[i], cum_at[i] = s, run
        grab_next = None
        if s[2] == word:
            if prev and prev[0] not in scale_rows:
                scale_rows[prev[0]], cum_at[prev[0]] = prev[1], prev[2]
            scale_rows[i], cum_at[i] = s, run
            grab_next = True
        prev = (i, s, run)
        if s[1] in readings and s[2] != word:
            same.append(s)
    # хвостовая отметка (весь список) не срабатывает: из-за совпадающих рангов
    # последний ранг меньше числа строк — добираем последнюю строку явно
    if pend and prev and prev[0] not in scale_rows:
        scale_rows[prev[0]], cum_at[prev[0]] = prev[1], prev[2]
    scale = [{"rank": int(scale_rows[i][0]), "word": scale_rows[i][2],
              "pmw": float(scale_rows[i][6]),
              "cum": 100.0 * cum_at[i] / LUW_TOKENS, "target": scale_rows[i][2] == word,
              "tie": r0 is not None and int(scale_rows[i][0]) == r0
                     and scale_rows[i][2] != word}
             for i in sorted(scale_rows)]

    pmw_l = sum(float(s[6]) for s in luw)
    freq_l = sum(int(s[5]) for s in luw)
    freq_s = sum(int(s[5]) for s in suw)
    band, label, note = verdict(pmw_l, WORD_BANDS, WORD_TAIL, ascending=False)

    def unit(s):
        return {"pos": s[3], "reading": s[1], "freq": int(s[5]), "pmw": float(s[6]),
                "rank": int(s[0]), "regs": parse_regs(s[7])}

    inner.sort(key=lambda s: -float(s[6]))
    inner_mass = sum(float(s[6]) for s in inner)
    same.sort(key=lambda s: -float(s[6]))

    writing, wr = [], {k: 0 for k in KINDS}
    cores = {}
    for s in rows("writing"):
        if s[1] != word:
            continue
        tot, parts = script_split(s[6])
        for k in KINDS:
            wr[k] += tot[k]
        for f, n, k in parts:
            if k == "кандзи":
                c = kanji_core(f)
                cores[c] = cores.get(c, 0) + n
        writing.append({"reading": s[0], "pos": s[2], "total": int(s[4]),
                        "parts": [{"form": f, "n": n, "kind": k} for f, n, k in parts]})

    return {
        "kind": "word", "found": True, "word": word,
        "band": band, "label": label, "note": note,
        "luw": [unit(s) for s in luw], "suw": [unit(s) for s in suw],
        "rank": r0, "pmw": pmw_l, "freq_l": freq_l, "freq_s": freq_s,
        "cum": next((x["cum"] for x in scale if x["rank"] == r0), None),
        "luw2_total": LUW2_TOTAL, "suw_total": SUW_TOTAL,
        "ratio": (freq_s / freq_l) if (suw and luw) else None,
        "scale": scale,
        "tied": tied,
        "inner": [{"word": s[2], "pmw": float(s[6]), "freq": int(s[5])} for s in inner],
        "inner_mass": inner_mass, "inner_freq": sum(int(s[5]) for s in inner),
        "writing": writing, "wr": wr,
        "kana": wr["хирагана"] + wr["катакана"], "kanji": wr["кандзи"],
        "other": wr["прочее"],
        "cores": sorted(cores.items(), key=lambda x: -x[1]),
        "same": [{"reading": s[1], "word": s[2], "pmw": float(s[6]), "pos": s[3]}
                 for s in same],
    }


# ========================================================= текстовый вывод
def head(title):
    print("\n" + title)
    print("-" * 72)


def render_text_kanji(d: dict):
    if not d["found"]:
        print(f'{d["ch"]}: в таблице знаков BCCWJ не встречается ни разу — '
              f'за пределами {KANJI_TOTAL} знаков, попавших в корпус.')
        return
    head(f'КАНДЗИ {d["ch"]}')
    print(f'ВЕРДИКТ    {d["label"]} — {d["note"]}')
    if d["rank"] <= d["core_rank"]:
        print(f'ранг       {d["rank"]} в рабочем списке из {d["core_rank"]} знаков '
              f'(они закрывают {num(d["core_cov"], 1)} % текста)')
    else:
        print(f'ранг       {d["rank"]} — за рабочим списком: до него уже кончились '
              f'{d["core_rank"]} знаков, закрывающих {num(d["core_cov"], 1)} % текста')
    print(f'частота    {num(d["pmw"])} pmw — вхождений на миллион символов текста '
          f'(кандзи среди них 30,3 %)')
    print(f'покрытие   знаки до этого ранга включительно дают {num(d["cum"])} % '
          f'из {num(d["tokens"], 0)} вхождений кандзи в корпусе')
    print(f'хвост      на оставшиеся {d["tail_n"]} '
          f'{plural(d["tail_n"], "знак", "знака", "знаков")} приходится '
          f'{num(d["tail_share"], 1)} % вхождений — имена, цитаты, разовые написания')

    head("ШКАЛА: ОПОРНЫЕ ТОЧКИ И БЛИЖАЙШИЕ СОСЕДИ")
    for s in d["scale"]:
        print(f'  ранг {s["rank"]:>5}  {pad(s["ch"], 4)} {num(s["pmw"]):>10} pmw   '
              f'кумулятивно {num(s["cum"]):>6} %'
              + ("   <<< искомый" if s["target"] else ""))

    head("ГДЕ ВСТРЕЧАЕТСЯ — написания из таблицы знаков")
    for f in d["forms"]:
        print(f'  {pad(f["form"], 14)} {num(f["n"], 0):>8}   '
              f'{num(f["share"], 1):>5} % вхождений знака')
    print(f'  перечисленные формы дают {num(d["forms_cover"], 1)} % всех вхождений знака')

    head("КАК САМОСТОЯТЕЛЬНОЕ СЛОВО")
    if d["standalone"]:
        for s in d["standalone"]:
            print(f'  {s["base"]:<5} {pad(s["pos"], 24)} pmw {num(s["pmw"]):>9}   '
                  f'ранг {s["rank"]} из {s["total"]}')
    else:
        print("  ни в luw2, ни в suw отдельным словом нет — знак только связанный")

    head("КРУПНЕЙШИЕ СЛОВА СО ЗНАКОМ (LUW2)")
    for w in d["nest"][:12]:
        print(f'  {pad(w["word"], 16)} {num(w["pmw"]):>9} pmw   '
              f'{num(w["share"], 1):>5} % гнезда   регистров {w["reg"]}/13')
    print(f'  всего {len(d["nest"])} слов, суммарная масса гнезда '
          f'{num(d["nest_mass"])} pmw')


def render_text_word(d: dict):
    head(f'СЛОВО {d["word"]}')
    if not d["found"]:
        print("Ни в luw2, ни в suw такой леммы нет.")
        if d["hits"]:
            print("Это написание принадлежит другим леммам — запусти по ним:")
            for h in d["hits"]:
                print(f'  {pad(h["lemma"], 14)} суммарно {h["n"]} вхождений')
        else:
            print("В таблице написаний такой формы тоже нет: "
                  "либо слово не встречается в корпусе, либо это не лемма "
                  "(леммы даются в нормализации UniDic: ちょっと -> 一寸).")
        return

    if d["luw"]:
        print(f'ВЕРДИКТ  {d["label"]} — {d["note"]}')
        print(f'LUW2 (реальные слова, {d["luw2_total"]} типов): ранг {d["rank"]}, '
              f'слова до него закрывают {num(d["cum"], 1)} % текста')
        for u in d["luw"]:
            print(f'  {pad(u["pos"], 22)} чтение {pad(u["reading"], 10)} '
                  f'freq {u["freq"]:>7}  pmw {num(u["pmw"]):>9}  ранг {u["rank"]}')
            top3 = sorted(u["regs"].items(), key=lambda x: -x[1])[:3]
            print(f'  {"":22} жанров {len(u["regs"])}/13, плотнее всего: '
                  + ", ".join(f'{REGISTERS[c]} {num(v, 1)}' for c, v in top3))
    else:
        print("LUW2 — леммы нет. В luw2 нет слов с частотой 1, "
              "значит как отдельное слово встречается не более раза.")

    print()
    if d["suw"]:
        print(f'SUW (короткие единицы, {d["suw_total"]} типов)')
        for u in d["suw"]:
            print(f'  {pad(u["pos"], 22)} чтение {pad(u["reading"], 10)} '
                  f'freq {u["freq"]:>7}  pmw {num(u["pmw"]):>9}  ранг {u["rank"]}')
            top3 = sorted(u["regs"].items(), key=lambda x: -x[1])[:3]
            print(f'  {"":22} жанров {len(u["regs"])}/13, плотнее всего: '
                  + ", ".join(f'{REGISTERS[c]} {num(v, 1)}' for c, v in top3))
    else:
        print("SUW — отдельной короткой единицей не встречается: "
              "разметка режет слово на части.")

    # ключ ко второму кейсу: сколько раз единица встречается вообще (SUW)
    # против того, сколько раз она стоит самостоятельным словом (LUW2).
    # Сравниваются абсолютные частоты: pmw у двух баз считаются от разных
    # знаменателей токенов и напрямую несравнимы.
    if d["ratio"]:
        k = d["ratio"]
        print(f'\n  SUW {d["freq_s"]} вхождений против LUW2 {d["freq_l"]} — '
              f'коэффициент {num(k)}×')
        print("  -> " + ratio_note(k))

    if d["scale"]:
        head("ШКАЛА LUW2: ЧТО СТОИТ НА СОСЕДНИХ И ОПОРНЫХ РАНГАХ")
        for s in d["scale"]:
            print(f'  ранг {s["rank"]:>6}{"=" if s["tie"] else " "} {pad(s["word"], 16)} '
                  f'{num(s["pmw"]):>10} pmw   кумулятивно {num(s["cum"], 1):>5} %'
                  + ("   <<< искомое" if s["target"] else ""))
        if d["tied"] > 1:
            print(f'  ранг {d["rank"]} делят {d["tied"]} '
                  + plural(d["tied"], "слово", "слова", "слов")
                  + " с одинаковой частотой (помечены «=»)")

    head("ВХОДИТ В СОСТАВ ДРУГИХ ЕДИНИЦ LUW2")
    if d["inner"]:
        for s in d["inner"][:12]:
            print(f'  {pad(s["word"], 18)} {num(s["pmw"]):>9} pmw   freq {s["freq"]}')
        if len(d["inner"]) > 12:
            print(f'  … и ещё {len(d["inner"]) - 12}')
        print(f'  всего {len(d["inner"])} единиц, суммарно {num(d["inner_mass"])} pmw, '
              f'freq {d["inner_freq"]}')
        if d["pmw"]:
            m = d["inner_mass"]
            print(f'  само слово {num(d["pmw"])} pmw против {num(m)} pmw в составных: '
                  f'на составные приходится {num(100 * m / (m + d["pmw"]), 1)} % '
                  f'совокупной массы')
    else:
        print("  ни в одну составную единицу luw2 не входит "
              "(здесь ищется только вхождение леммы целиком)")

    head("ЗАПИСЬ: ЧЕМ СЛОВО НАБРАНО (таблица написаний)")
    if not d["writing"]:
        print("  этой леммы в таблице написаний нет")
    else:
        for w in d["writing"]:
            print(f'  {d["word"]} / {w["reading"]}  {w["pos"]}  всего {w["total"]}')
            for p in w["parts"]:
                print(f'      {pad(p["form"], 14)} {p["n"]:>7}  {p["kind"]}')
        tot = sum(d["wr"].values())
        if tot:
            print("  ИТОГО  " + ", ".join(
                f'{k} {d["wr"][k]} ({num(100 * d["wr"][k] / tot, 1)} %)'
                for k in KINDS if d["wr"][k]))
            if len(d["cores"]) > 1:
                print("  знаком — разные написания: " + ", ".join(
                    f"{c} {n}" for c, n in d["cores"]))
            print("  -> " + script_note(d))

    head("ДРУГИЕ ЛЕММЫ С ТЕМ ЖЕ ЧТЕНИЕМ (LUW2)")
    if d["same"]:
        for s in d["same"][:8]:
            print(f'  {pad(s["reading"], 10)} {pad(s["word"], 14)} '
                  f'{num(s["pmw"]):>9} pmw   {s["pos"]}')
    else:
        print("  таких нет")


def ratio_note(k: float) -> str:
    if k < 1.1:
        return ("почти всегда стоит самостоятельным словом, "
                "в состав других единиц практически не входит")
    if k < 2:
        return (f'примерно {num(100 * (1 - 1 / k), 0)} % вхождений морфемы '
                "приходится на более длинные единицы")
    return (f'самостоятельным словом идёт лишь {num(100 / k, 0)} % вхождений: '
            "морфема живёт в основном внутри других единиц")


def script_note(d: dict) -> str:
    """Вывод о записи слова, собранный из чисел этого запроса."""
    w, tot = d["wr"], sum(d["wr"].values())
    if not tot:
        return "написаний в таблице нет"
    kj, hi, ka, ot = (w["кандзи"] / tot, w["хирагана"] / tot,
                      w["катакана"] / tot, w["прочее"] / tot)
    if not kj:
        top, sh = max((("хираганой", hi), ("катаканой", ka),
                       ("латиницей, цифрами и символами", ot)), key=lambda x: x[1])
        return (f"иероглифической записи у слова нет вовсе: {num(100 * sh, 1)} % "
                f"вхождений набрано {top}")
    if kj >= 0.85:
        s = (f"знаком набрано {num(100 * kj, 1)} % вхождений — встретив слово "
             "в тексте, знак почти наверняка увидишь")
    elif kj >= 0.5:
        s = (f"знаком набрано {num(100 * kj, 1)} % вхождений: запись знаком "
             f"преобладает, но {num(100 * (1 - kj), 1)} % идут без него")
    elif kj >= 0.15:
        s = (f"знаком набрано лишь {num(100 * kj, 1)} % вхождений — чаще слово "
             "попадётся на глаза без него")
    else:
        s = (f"знаком слово почти не пишут: {num(100 * kj, 1)} % вхождений, "
             "учить начертание ради него смысла мало")
    if ot >= 0.1:
        s += (f"; ещё {num(100 * ot, 1)} % — не кана и не кандзи "
              "(латиница, цифры, символы)")
    elif hi >= 0.1 and ka >= 0.1:
        s += (f"; кана делится надвое: {num(100 * hi, 1)} % хираганой "
              f"и {num(100 * ka, 1)} % катаканой")
    elif ka >= 0.2 and hi < 0.05:
        s += f"; без знака слово идёт катаканой ({num(100 * ka, 1)} %)"
    return s


# ============================================================= HTML-вывод
# Колонки, выровненные пробелами, в японском тексте не держатся: знак занимает
# два знакоместа, а шрифт получателя об этом не всегда знает. Поэтому страница
# не выравнивает ничего пробелами — величины показаны длиной полос.

CSS = """
:root{
  --ground:#f7f7f4; --surface:#fff; --sunk:#f1f1ec;
  --ink:#16181d; --ink2:#565c67; --ink3:#8a9099;
  --line:#e4e4de; --accent:#27437f; --accent-soft:#e9eef8;
  --b0:#1e3a6e; --b1:#35619f; --b2:#6e93c4; --b3:#b08a4a; --b4:#a65c3f; --b5:#7a4a3e;
  --kana:#b08a4a; --kata:#a65c3f; --other:#8a9099; --kanji:#27437f;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#121417; --surface:#191c21; --sunk:#15181c;
    --ink:#e9eaed; --ink2:#a2a8b2; --ink3:#6e757f;
    --line:#2a2e35; --accent:#8faee8; --accent-soft:#1d2432;
    --b0:#6f93d8; --b1:#5c86c8; --b2:#7fa0c8; --b3:#d0a85f; --b4:#ce7a57; --b5:#a9705e;
    --kana:#d0a85f; --kata:#ce7a57; --other:#6e757f; --kanji:#8faee8;
  }
}
:root[data-theme="dark"]{
  --ground:#121417; --surface:#191c21; --sunk:#15181c;
  --ink:#e9eaed; --ink2:#a2a8b2; --ink3:#6e757f;
  --line:#2a2e35; --accent:#8faee8; --accent-soft:#1d2432;
  --b0:#6f93d8; --b1:#5c86c8; --b2:#7fa0c8; --b3:#d0a85f; --b4:#ce7a57; --b5:#a9705e;
  --kana:#d0a85f; --kata:#ce7a57; --other:#6e757f; --kanji:#8faee8;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font:15px/1.55 "Segoe UI",-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;
  font-variant-numeric:tabular-nums;
}
.jp{font-family:"Hiragino Mincho ProN","Yu Mincho",YuMincho,"Noto Serif JP","MS PMincho",serif}
.page{max-width:880px; margin:0 auto; padding:28px 20px 64px; display:flex; flex-direction:column; gap:20px}

.hero{display:flex; gap:22px; align-items:flex-start; flex-wrap:wrap;
  background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:22px 24px}
.glyph{font-size:76px; line-height:1; color:var(--ink)}
.glyph.word{font-size:46px}
.hero-body{flex:1 1 320px; display:flex; flex-direction:column; gap:10px; min-width:0}
.badgerow{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap}
.badge{display:inline-block; padding:4px 11px; border-radius:4px;
  font-size:12px; font-weight:600; letter-spacing:.09em; color:#fff; background:var(--b1)}
.bgloss{font-size:12.5px; color:var(--ink3)}
.badge.b0{background:var(--b0)} .badge.b1{background:var(--b1)} .badge.b2{background:var(--b2)}
.badge.b3{background:var(--b3)} .badge.b4{background:var(--b4)} .badge.b5{background:var(--b5)}
.lead{margin:0; color:var(--ink2); font-size:14px; max-width:60ch; text-wrap:balance}
.reading{color:var(--ink2); font-size:13px; letter-spacing:.06em}

.metrics{display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:10px; overflow:hidden}
.metric{background:var(--surface); padding:13px 15px; display:flex; flex-direction:column; gap:3px}
.metric .k{font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink3)}
.metric .v{font-size:21px; font-weight:600; line-height:1.2}
.metric .s{font-size:12px; color:var(--ink2)}

.card{background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:18px 20px;
  display:flex; flex-direction:column; gap:12px}
h2{margin:0; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink3); font-weight:600}
.note{margin:0; font-size:13px; color:var(--ink2); max-width:64ch}
.note b{color:var(--ink); font-weight:600}

.strip{position:relative; padding:26px 0 0}
.segs{display:flex; height:26px; border-radius:5px; overflow:hidden}
.seg{position:relative; flex:0 0 auto; min-width:0; display:flex; align-items:center;
  justify-content:center; padding:0 2px;
  font-size:10.5px; letter-spacing:.04em; color:#fff; white-space:nowrap; overflow:hidden}
.mark{position:absolute; top:0; transform:translateX(-50%); display:flex; flex-direction:column;
  align-items:center; pointer-events:none}
.mark .lbl{font-size:12px; font-weight:600; white-space:nowrap; background:var(--surface);
  padding:0 5px; border-radius:3px}
.mark .pin{width:2px; height:34px; background:var(--ink)}
.mpin{position:absolute; width:2px; background:var(--ink); transform:translateX(-50%)}
/* .mark .lbl — потомок .mark, к отдельным подписям не применяется: стиль
   повторён здесь целиком, фон обязателен — он перекрывает чужие черты */
.mlbl{position:absolute; transform:translateX(-50%); line-height:18px;
  font-size:12px; font-weight:600; white-space:nowrap; background:var(--surface);
  padding:0 5px; border-radius:3px}
.tick{position:absolute; top:52px; transform:translateX(-50%); display:flex;
  flex-direction:column; align-items:center; pointer-events:none}
.tick i{width:1px; height:7px; background:var(--ink3)}
.tick span{font-size:10.5px; color:var(--ink3); white-space:nowrap; margin-top:2px}
.tick b{font-size:10.5px; font-weight:600; color:var(--ink2); white-space:nowrap; margin-top:2px}
.tick b+span{margin-top:0}
.ends{display:flex; justify-content:space-between; font-size:11px; color:var(--ink3);
  margin-top:30px}
.strip.tall .ends{margin-top:48px}

table.cmp td{vertical-align:top}
table.cmp td.w{font-size:20px; line-height:1.25}
table.cmp .sub{display:block; font-size:11.5px; color:var(--ink3); font-weight:400}
table.cmp tr.off td{color:var(--ink3)}
h1.tt{margin:0; font-size:22px; font-weight:600}

.bars{display:grid; grid-template-columns:auto 1fr auto; gap:5px 12px; align-items:center}
.bars .n{font-size:14px; min-width:0; overflow-wrap:anywhere}
.bars .t{position:relative; height:9px; background:var(--sunk); border-radius:5px}
.bars .t i{overflow:hidden}
.bars .t em{position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--ink3);
  opacity:.55; border-radius:1px}
.bars .t i.dim{background:var(--ink3); opacity:.4}
.bars .v.off{color:var(--ink3)}
.bars .t i{display:block; height:100%; background:var(--accent); border-radius:5px}
.bars .t i.alt,.bars .t i.s-hira{background:var(--kana)}
.bars .t i.s-kata{background:var(--kata)}
.bars .t i.s-other{background:var(--other)}
.bars .t i.s-kanji{background:var(--kanji)}
.bars .v{font-size:12.5px; color:var(--ink2); white-space:nowrap}
.bars .row-hi .n,.bars .row-hi .v{font-weight:700; color:var(--ink)}

.split{display:flex; height:30px; border-radius:5px; overflow:hidden; font-size:12px; color:#fff}
.split div{flex:0 0 auto; min-width:0; display:flex; align-items:center;
  justify-content:center; white-space:nowrap; overflow:hidden}
.split .s-kanji{background:var(--kanji)} .split .s-hira{background:var(--kana)}
.split .s-kata{background:var(--kata)} .split .s-other{background:var(--other)}
.legend{display:flex; gap:16px; font-size:12px; color:var(--ink2); flex-wrap:wrap}
.legend i{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:5px}

.genres{display:flex; flex-direction:column; gap:9px}
.grow{display:flex; gap:7px; align-items:center; flex-wrap:wrap}
.glabel{font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:var(--ink3);
  flex:0 0 118px}
.chip{font-size:12.5px; padding:3px 10px; border-radius:999px;
  border:1px solid var(--line); color:var(--ink3)}
.chip.g1{background:var(--b0); color:#fff; border-color:transparent; font-weight:600}
.chip.g2{background:var(--b1); color:#fff; border-color:transparent}
.chip.g3{background:var(--b2); color:#fff; border-color:transparent}
@media (max-width:520px){ .glabel{flex:0 0 100%} }
.dots{display:inline-flex; gap:3px; vertical-align:middle}
.dots i{width:7px; height:7px; border-radius:50%; background:var(--line)}
.dots i.on{background:var(--accent)}

table{border-collapse:collapse; width:100%; font-size:13px}
th,td{text-align:left; padding:6px 0; border-bottom:1px solid var(--line); vertical-align:baseline}
th+th,td+td{padding-left:16px}
th{font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--ink3); font-weight:600}
td.r,th.r{text-align:right; white-space:nowrap}
tr.hi td{background:var(--accent-soft); font-weight:600}
.scroll{overflow-x:auto}
td .tie{color:var(--ink3); font-weight:400; margin-left:2px}

details{border-top:1px solid var(--line); padding-top:10px}
summary{cursor:pointer; font-size:12.5px; color:var(--accent); font-weight:600; list-style:none}
summary::-webkit-details-marker{display:none}
summary:before{content:"▸ "; }
details[open] summary:before{content:"▾ "}
summary:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:3px}
details>*:not(summary){margin-top:12px}

.gloss{display:grid; grid-template-columns:auto 1fr; gap:9px 16px; font-size:13px}
.gloss dt{font-weight:600; white-space:nowrap}
.gloss dd{margin:0; color:var(--ink2)}
.nb{white-space:nowrap}
@media (max-width:520px){ .gloss{grid-template-columns:1fr; gap:2px 0} .gloss dd{margin-bottom:8px} }
footer{font-size:12px; color:var(--ink3); text-align:center; padding-top:6px}
@media (max-width:520px){ .glyph{font-size:60px} .page{padding:18px 14px 48px} }
"""


def esc(s) -> str:
    return _h.escape(str(s))


KIND_CLS = {"\u043a\u0430\u043d\u0434\u0437\u0438": "s-kanji", "\u0445\u0438\u0440\u0430\u0433\u0430\u043d\u0430": "s-hira",
            "\u043a\u0430\u0442\u0430\u043a\u0430\u043d\u0430": "s-kata", "\u043f\u0440\u043e\u0447\u0435\u0435": "s-other"}
KIND_VAR = {"\u043a\u0430\u043d\u0434\u0437\u0438": "kanji", "\u0445\u0438\u0440\u0430\u0433\u0430\u043d\u0430": "kana",
            "\u043a\u0430\u0442\u0430\u043a\u0430\u043d\u0430": "kata", "\u043f\u0440\u043e\u0447\u0435\u0435": "other"}


def bar_rows(items, hi=None):
    """items: [(имя, длина полосы 0..100, подпись, alt)]

    alt — либо флаг «покрасить вторым цветом», либо готовое имя css-класса
    (запись слова красится в четыре цвета, одного флага не хватает).
    """
    out = ['<div class="bars">']
    for name, w, val, alt in items:
        cls = ' class="row-hi"' if hi and name == hi else ""
        icls = alt if isinstance(alt, str) else ("alt" if alt else "")
        out.append(
            f'<span class="n jp"{cls}>{esc(name)}</span>'
            f'<span class="t"><i class="{icls}" '
            f'style="width:{max(w, 0.6):.2f}%"></i></span>'
            f'<span class="v"{cls}>{esc(val)}</span>')
    out.append("</div>")
    return "".join(out)


def genre_rows(regs: dict, base: float) -> str:
    """Столбики по 13 жанрам плюс опорная линия — средняя плотность по корпусу.

    Смысл именно в отношении к средней: 206 pmw в бестселлерах против 68,7
    по корпусу — это «втрое плотнее», и такой вывод читается сразу, а голое
    число само по себе ничего не говорит.
    """
    order = sorted(REGISTERS, key=lambda c: -regs.get(c, 0.0))
    mx = max([regs.get(c, 0.0) for c in order] + [base]) or 1.0
    ref = base / mx * 100
    out = ['<div class="bars">']
    for c in order:
        v = regs.get(c, 0.0)
        if v <= 0:
            bar = '<span class="t"><em style="left:%.2f%%"></em></span>' % ref
            val = '<span class="v off">не встречается</span>'
        else:
            ratio = v / base if base else 0.0
            bar = ('<span class="t"><i class="%s" style="width:%.2f%%"></i>'
                   '<em style="left:%.2f%%"></em></span>'
                   % ("" if ratio >= 1 else "dim", max(v / mx * 100, 0.8), ref))
            # у редких жанров отношение уходит в сотые: «×0,0» — не число
            digits = 1 if ratio >= 0.1 else 2
            val = ('<span class="v">' + num(v, 1) + ' pmw · ×'
                   + num(ratio, digits) + '</span>')
        out.append('<span class="n">' + esc(REGISTERS[c]) + '</span>' + bar + val)
    out.append("</div>")
    return "".join(out)


def dots(n, total=13):
    return ('<span class="dots">'
            + "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(total))
            + f'</span> <span class="v">{n}/{total}</span>')


def strip(segments, pos, label, left_end, right_end, ticks=()):
    """segments: [(доля ширины в %, подпись, класс цвета)]; pos — метка в %;
    ticks: [(позиция в %, подпись)] — внешние ориентиры под полосой."""
    # подпись в узком отрезке всё равно обрежется на полуслове — там её нет
    segs = "".join(
        f'<div class="seg" style="width:{w:.4f}%;background:var(--{c})">'
        f'{esc(t) if w >= 9 else ""}</div>'
        for w, t, c in segments)
    pos = min(max(pos, 0.0), 100.0)
    # Засечки рядом сливаются в кашу: держим минимальный зазор по ширине.
    kept, last = [], -99.0
    for x, t in ticks:
        if x - last >= 9.0:
            kept.append((x, t))
            last = x
    ticks = kept
    two = any(not isinstance(t, str) for _, t in ticks)
    # подпись засечки: строка — одна строчка, пара — две (сверху главное число)
    tk = "".join(
        f'<div class="tick" style="left:{min(max(x, 0.0), 100.0):.2f}%"><i></i>'
        + (f'<span>{esc(t)}</span>' if isinstance(t, str)
           else f'<b>{esc(t[0])}</b><span>{esc(t[1])}</span>')
        + '</div>' for x, t in ticks)
    return (f'<div class="strip{" tall" if two else ""}"><div class="mark" style="left:{pos:.2f}%">'
            f'<span class="lbl jp">{esc(label)}</span><span class="pin"></span></div>'
            f'<div class="segs">{segs}</div>{tk}'
            f'<div class="ends"><span>{esc(left_end)}</span>'
            f'<span>{esc(right_end)}</span></div></div>')


def page(title, body):
    # разряды числа рвались переносом строки: "таких слов 4" / "955"
    body = re.sub(r"(?<=\d) (?=\d)", "\u00a0", body)
    return ("<!doctype html>\n<html lang=\"ru\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
            f'<main class="page">\n{body}\n'
            '<footer>BCCWJ · таблицы kanji / luw2 / suw / writing · '
            'шкалы описаны в docs/scale.md</footer>\n'
            "</main>\n</body>\n</html>\n")


TERMS_COMMON = [
    ("pmw", "частота на миллион. Знаменатель у слов и у кандзи разный: у слов "
            "это миллион слов текста, у кандзи — миллион <b>символов</b>, включая "
            "кану и пунктуацию (кандзи среди них 30,3 %). Поэтому pmw слова и pmw "
            "знака сравнивать между собой нельзя — только внутри своей таблицы."),
    ("вхождение", "один случай в тексте. «Тип» — уникальная единица: слово, "
                  "встретившееся 5 725 раз, — это один тип и 5 725 вхождений."),
    ("кумулятивное покрытие",
     "какую долю текста закрывают все единицы до этого ранга включительно."),
    ("BCCWJ", "сбалансированный корпус современного письменного японского: "
              "около 82 млн слов из книг, журналов, газет, сети и документов."),
]
TERMS_KANJI = [
    ("словоформа", "знак в том виде, в каком он стоит в тексте. Например "
                   '<span class="nb jp">頷い</span> — это не слово, а общая основа форм '
                   '<span class="nb jp">頷いた</span> и <span class="nb jp">頷いて</span>.'),
    ("лемма", "словарная форма. Несколько словоформ сводятся к одной лемме, поэтому "
              "список форм и список слов упорядочены по-разному — это не расхождение "
              "в данных, а два разреза одних и тех же вхождений."),
    ("гнездо", "все слова корпуса, в которых встречается этот знак."),
]
TERMS_WORD = [
    ("лемма", "словарная форма слова. Все формы считаются вместе: например "
              '<span class="nb jp">頷いた</span>, <span class="nb jp">頷いて</span> и '
              '<span class="nb jp">頷きます</span> — это одна лемма '
              '<span class="nb jp">頷く</span>.'),
    ("LUW2", "«длинные единицы» — слова так, как их выделяет разметка корпуса. "
             "Ранг и вердикт берутся отсюда."),
    ("SUW", "«короткие единицы» — та же разметка, но мельче: длинное сложение "
            "распадается на части. Нужна ровно для одного сравнения — в разделе "
            "«Слово или морфема»."),
    ("регистры", "из скольких 13 подкорпусов BCCWJ (книги, газеты, блоги, "
                 "парламент и так далее) слово вообще встречается. Меньше регистров "
                 "— уже сфера употребления."),
]


def glossary(terms) -> str:
    # определения — литералы модуля, поэтому вставляются как есть: в них
    # нужна разметка <span class="nb">, чтобы японский пример не рвался
    dl = "".join("<dt>" + esc(t) + "</dt><dd>" + d + "</dd>" for t, d in terms)
    return ('<section class="card"><h2>Термины</h2><dl class="gloss">' + dl
            + '</dl></section>')


KANJI_SHORT = ["ядро", "очень частый", "обычный", "на краю", "редкий", "хвост"]
WORD_SHORT = ["очень частое", "частое", "обычное", "редкое", "на грани"]


def html_kanji(d: dict) -> str:
    if not d["found"]:
        body = ('<div class="hero"><div class="glyph jp">' + esc(d["ch"]) + '</div>'
                '<div class="hero-body"><span class="badge b5">НЕ ВСТРЕЧАЕТСЯ</span>'
                '<p class="lead">В таблице знаков BCCWJ этого знака нет ни разу — он за '
                'пределами ' + str(KANJI_TOTAL) + ' знаков, попавших в корпус.</p>'
                '</div></div>')
        return page(esc(d["ch"]) + " — нет в корпусе", body)

    bounds = [0] + [b[0] for b in KANJI_BANDS] + [d["core_rank"]]
    labels = KANJI_SHORT[:5]
    if d["rank"] > d["core_rank"]:
        bounds.append(d["total"])
        labels = KANJI_SHORT[:6]
    domain = bounds[-1]
    segs = [((bounds[i + 1] - bounds[i]) / domain * 100, labels[i], "b%d" % i)
            for i in range(len(bounds) - 1)]

    parts = []

    # Расшифровка рядом с ярлыком говорит про сам знак, а не про полосу:
    # границы полос ушли засечками на шкалу.
    kgloss = ("ранг " + num(d["rank"], 0) + " из " + num(d["core_rank"], 0)
              if d["rank"] <= d["core_rank"]
              else "ранг " + num(d["rank"], 0) + " — за рабочим списком ("
                   + num(d["core_rank"], 0) + ")")

    if d["standalone"]:
        life = "Встречается и как самостоятельное слово."
    else:
        life = "Отдельным словом знак не встречается — он живёт только внутри слов."
    if d["nest"]:
        t = d["nest"][0]
        life += (" Больше всего вхождений даёт <b class=\"jp\">" + esc(t["word"])
                 + "</b> — " + num(t["share"], 1) + " % гнезда.")
    parts.append('<div class="hero"><div class="glyph jp">' + esc(d["ch"]) + '</div>'
                 '<div class="hero-body">'
                 '<div class="badgerow"><span class="badge b' + str(d["band"]) + '">'
                 + esc(d["label"]) + '</span><span class="bgloss">' + esc(kgloss)
                 + '</span></div>'
                 '<p class="lead">Попадается ' + once_in(d["pmw"], "символов")
                 + ' текста.</p>'
                 '<p class="lead">' + life + '</p></div></div>')

    parts.append(
        '<div class="metrics">'
        '<div class="metric"><span class="k">ранг</span><span class="v">'
        + num(d["rank"], 0) + '</span><span class="s">'
        + ('из ' + str(d["core_rank"]) + ' рабочих знаков'
           if d["rank"] <= d["core_rank"]
           else 'за рабочим списком (' + str(d["core_rank"]) + ')') + '</span></div>'
        '<div class="metric"><span class="k">частота</span><span class="v">'
        + num(d["pmw"]) + '</span><span class="s">pmw · '
        + once_in(d["pmw"], "символов") + '</span></div>'
        '<div class="metric"><span class="k">покрытие</span><span class="v">'
        + num(d["cum"]) + ' %</span><span class="s">всех кандзи закрыто до него'
        '</span></div>'
        '<div class="metric"><span class="k">гнездо</span><span class="v">'
        + str(len(d["nest"])) + '</span><span class="s">'
        + (plural(len(d["nest"]), "слово", "слова", "слов") + '; '
           + num(d["nest"][0]["share"], 0) + ' % массы — одно'
           if d["nest"] else "слов") + '</span></div></div>')

    quarter = d["rank"] / d["core_rank"]
    if quarter <= 0.25:
        place = "Это верхняя четверть списка: без таких знаков текст не читается."
    elif quarter <= 0.5:
        place = "Вторая четверть списка: знак встречается регулярно в любом тексте."
    elif quarter <= 0.75:
        place = "Третья четверть: знак нужен, но не в первую очередь."
    elif quarter <= 1.0:
        place = ("Последняя четверть рабочего списка: знак настоящий, но всё, что "
                 "выше него, окупается раньше.")
    else:
        place = ("Знак за пределами рабочего списка — в той части, которую делят "
                 "имена собственные, цитаты и разовые написания.")
    own = 100.0 * d["freq"] / d["tokens"]
    ahead = d["rank"] - 1
    parts.append(
        '<section class="card"><h2>Место на шкале частот</h2>'
        + strip(segs, d["rank"] / domain * 100, d["ch"],
                "ранг 1 · " + once_in(d["pmw_at"][1], "символов"),
                "ранг " + num(domain, 0) + " · " + once_in(d["pmw_at"][domain], "символов"),
                ticks=[(b / domain * 100, (num(b, 0), per_words(d["pmw_at"][b])))
                       for b in bounds[1:-1]])
        + '<p class="note">Частотнее — ' + num(ahead, 0) + ' '
        + plural(ahead, "знак", "знака", "знаков") + '. Собственный вклад '
        + esc(d["ch"]) + ' в покрытие текста — ' + num(own, 3)
        + ' п.п. ' + place + '</p>'
        + '<div class="scroll"><table><tr><th class="r">ранг</th><th>знак</th>'
          '<th class="r">pmw</th><th class="r">как часто</th>'
          '<th class="r">кумулятивно</th></tr>'
        + "".join('<tr class="' + ("hi" if x["target"] else "") + '"><td class="r">'
                  + num(x["rank"], 0) + '</td><td class="jp">' + esc(x["ch"])
                  + '</td><td class="r">' + num(x["pmw"]) + '</td><td class="r">'
                  + once_in(x["pmw"], "символов") + '</td><td class="r">'
                  + num(x["cum"]) + ' %</td></tr>' for x in d["scale"])
        + '</table></div></section>')

    # ---- гнездо идёт первым: сначала «сколько слов даст знак», потом «в каком
    # виде я его увижу». Порядок обратный тому, как данные лежат в таблице.
    sec_nest = ""
    if d["nest"]:
        mxn = max(w["pmw"] for w in d["nest"])

        def nrow(w):
            return (w["word"], w["pmw"] / mxn * 100,
                    num(w["pmw"]) + " pmw  ·  " + num(w["share"], 1) + " %", False)

        rest = ""
        if len(d["nest"]) > 10:
            rest = ('<details><summary>показать всё гнездо: ' + str(len(d["nest"]))
                    + ' слов</summary>' + bar_rows([nrow(w) for w in d["nest"][10:]])
                    + '</details>')
        top = d["nest"][0]
        need, acc = 0, 0.0
        for w in d["nest"]:
            need += 1
            acc += w["share"]
            if acc >= 80:
                break
        if top["share"] >= 80:
            said = ('Знак почти однословный: ' + num(top["share"], 1)
                    + ' % его вхождений даёт одно слово <b class="jp">'
                    + esc(top["word"]) + '</b>. Выучить знак — значит выучить это '
                      'слово; переноса на другую лексику ждать не стоит.')
        elif need <= 3:
            said = ('Четыре пятых вхождений держат ' + str(need) + ' '
                    + plural(need, "слово", "слова", "слов")
                    + '. Знак окупается быстро.')
        else:
            said = ('Вхождения размазаны: чтобы закрыть четыре пятых, нужно '
                    + str(need) + ' ' + plural(need, "слово", "слова", "слов")
                    + '. Это строительный материал, а не одно слово.')
        sec_nest = ('<section class="card"><h2>Словарные слова со знаком</h2>'
                    + bar_rows([nrow(w) for w in d["nest"][:10]])
                    + '<p class="note">' + said + ' Всего в гнезде '
                    + str(len(d["nest"])) + ' '
                    + plural(len(d["nest"]), "слово", "слова", "слов") + '.</p>'
                    + rest + '</section>')

    # ---- формы: в каком виде знак реально попадается на глаза
    mx = max((f["n"] for f in d["forms"]), default=1)

    def frow(f):
        return (f["form"], f["n"] / mx * 100,
                num(f["n"], 0) + "  ·  " + num(f["share"], 1) + " %", False)

    rest = ""
    if len(d["forms"]) > 10:
        rest = ('<details><summary>показать все написания: ' + str(len(d["forms"]))
                + '</summary>' + bar_rows([frow(f) for f in d["forms"][10:]]) + '</details>')
    said = ""
    if d["forms"]:
        f0 = d["forms"][0]
        said = ('Узнавать знак придётся прежде всего в форме <b class="jp">'
                + esc(f0["form"]) + '</b> — на неё приходится ' + num(f0["share"], 1)
                + ' % всех его вхождений.')
        if d["nest"] and f0["form"] != d["nest"][0]["word"]:
            said += (' Это словоформа, а не слово: в списке выше те же вхождения '
                     'сложены в словарные формы, поэтому первая строка там другая.')
    sec_forms = ('<section class="card"><h2>Формы в тексте</h2>'
                 + bar_rows([frow(f) for f in d["forms"][:10]])
                 + '<p class="note">' + said + '</p>' + rest + '</section>')

    parts.append(sec_nest)
    parts.append(sec_forms)

    if d["standalone"]:
        tr = "".join('<tr><td>' + esc(s["base"]) + '</td><td>' + esc(s["pos"])
                     + '</td><td class="r">' + num(s["pmw"]) + '</td><td class="r">'
                     + str(s["rank"]) + " из " + str(s["total"]) + '</td></tr>'
                     for s in d["standalone"])
        parts.append('<section class="card"><h2>Как самостоятельное слово</h2>'
                     '<div class="scroll"><table><tr><th>база</th><th>разметка</th>'
                     '<th class="r">pmw</th><th class="r">ранг</th></tr>' + tr
                     + '</table></div></section>')

    parts.append(glossary(TERMS_KANJI + TERMS_COMMON))
    return page(d["ch"] + " — частотность BCCWJ", "\n".join(parts))


def word_pos(pmw: float) -> float:
    """Позиция на логарифмической шкале pmw: 1000 pmw -> 0 %, 0,01 pmw -> 100 %.
    Концы берутся из WORD_SCALE_HI/LO, чтобы засечки границ полос считались
    по той же формуле, что и метка слова."""
    import math
    hi, lo = math.log10(WORD_SCALE_HI), math.log10(WORD_SCALE_LO)
    return (hi - math.log10(max(pmw, lo / 10))) / (hi - lo) * 100.0


def html_word(d: dict) -> str:
    if not d["found"]:
        if d["hits"]:
            tip = ('Это написание принадлежит другим леммам — запусти по ним:<br>'
                   + "<br>".join('<b class="jp">' + esc(h["lemma"]) + '</b> — суммарно '
                                 + str(h["n"]) + ' вхождений' for h in d["hits"]))
        else:
            tip = ('В таблице написаний такой формы тоже нет: либо слово не встречается '
                   'в корпусе, либо это не лемма (леммы даются в нормализации UniDic: '
                   'ちょっと → 一寸).')
        body = ('<div class="hero"><div class="glyph word jp">' + esc(d["word"]) + '</div>'
                '<div class="hero-body"><span class="badge b5">НЕ НАЙДЕНО</span>'
                '<p class="lead">' + tip + '</p></div></div>')
        return page(d["word"] + " — не найдено", body)

    parts = []
    reading = d["luw"][0]["reading"] if d["luw"] else (
        d["suw"][0]["reading"] if d["suw"] else "")
    posname = d["luw"][0]["pos"] if d["luw"] else (
        d["suw"][0]["pos"] if d["suw"] else "")

    tot = sum(d["wr"].values())
    lead2 = ""
    if tot:
        # script_note сам начинается с «знаком набрано N %» — отдельная
        # фраза перед ним дублировала это число слово в слово.
        lead2 = script_note(d).capitalize() + "."
    # Расшифровка рядом с ярлыком говорит про само слово, а не про полосу:
    # границы полос ушли засечками на шкалу, дублировать их в шапке незачем.
    gloss = (('Ранг ' + num(d["rank"], 0) + ' · ') if d["rank"] else "") \
        + num(d["pmw"]) + " pmw"
    lead1 = ""
    if d["rank"]:
        lead1 = ('Чаще него — ' + num(d["rank"] - 1, 0) + ' '
                 + plural(d["rank"] - 1, "слово", "слова", "слов") + ' из '
                 + num(d["luw2_total"], 0) + '.')
    parts.append('<div class="hero"><div class="glyph word jp">' + esc(d["word"]) + '</div>'
                 '<div class="hero-body">'
                 '<div class="badgerow"><span class="badge b' + str(d["band"]) + '">'
                 + esc(d["label"]) + '</span><span class="bgloss">' + esc(gloss)
                 + '</span></div>'
                 '<span class="reading jp">' + esc(reading) + ' · ' + esc(posname) + '</span>'
                 + ('<p class="lead">' + lead1 + '</p>' if lead1 else "")
                 + ('<p class="lead">' + lead2 + '</p>' if lead2 else "")
                 + '</div></div>')

    cum = num(d["cum"], 1) + " %" if d["cum"] is not None else "—"
    rank = num(d["rank"], 0) if d["rank"] else "—"
    kjshare = num(100 * d["kanji"] / tot, 1) + " %" if tot else "—"
    kjsub = "от всех вхождений в тексте"
    if tot and d["other"] / tot >= 0.05:
        kjsub = ("прочей записью — " + num(100 * d["other"] / tot, 1)
                 + " % (латиница, цифры)")
    elif tot and d["kana"]:
        kjsub = ("каной — " + num(100 * d["kana"] / tot, 1) + " %")
    parts.append(
        '<div class="metrics">'
        '<div class="metric"><span class="k">ранг LUW2</span><span class="v">' + rank
        + '</span><span class="s">из ' + num(d["luw2_total"], 0)
        + ' разных слов корпуса</span></div>'
        '<div class="metric"><span class="k">частота</span><span class="v">'
        + num(d["pmw"]) + '</span><span class="s">pmw · '
        + once_in(d["pmw"], "слов") + '</span></div>'
        '<div class="metric"><span class="k">покрытие</span><span class="v">' + cum
        + '</span><span class="s">текста состоит из слов до него</span></div>'
        '<div class="metric"><span class="k">пишется знаком</span><span class="v">'
        + kjshare + '</span><span class="s">' + esc(kjsub) + '</span></div></div>')

    segs = [(20.0, WORD_SHORT[i], "b%d" % i) for i in range(5)]
    tr = "".join('<tr class="' + ("hi" if a["target"] else "") + '">'
                 '<td class="r">' + num(a["rank"], 0)
                 + ('<span class="tie">=</span>' if a["tie"] else "")
                 + '</td><td class="jp">'
                 + esc(a["word"]) + '</td><td class="r">' + num(a["pmw"])
                 + '</td><td class="r">' + once_in(a["pmw"], "слов")
                 + '</td><td class="r">' + num(a["cum"], 1) + ' %</td></tr>'
                 for a in d["scale"])
    # Ранги в luw2 повторяются: одинаковая частота — один ранг. Соседи берутся
    # по факту, строкой выше и строкой ниже, поэтому в колонке рангов может
    # трижды стоять одно число. Молча это выглядит как ошибка — помечаем.
    tie_note = ""
    if d["tied"] > 1:
        tie_note = ('<p class="note">Ранг ' + num(d["rank"], 0) + ' делят '
                    + num(d["tied"], 0) + ' '
                    + plural(d["tied"], "слово", "слова", "слов")
                    + ' с одинаковой частотой; «=» в таблице помечает такие '
                    'строки. Порядок внутри одного ранга ничего не значит.</p>')
    parts.append('<section class="card"><h2>Место на шкале частот</h2>'
                 + strip(segs, word_pos(d["pmw"]), d["word"],
                         "раз на " + per_words(WORD_SCALE_HI) + " слов",
                         "раз на " + per_words(WORD_SCALE_LO) + " слов",
                         ticks=[(word_pos(b[0]), per_words(b[0])) for b in WORD_BANDS])
                 + '<div class="scroll"><table><tr><th class="r">ранг</th><th>слово</th>'
                 '<th class="r">pmw</th><th class="r">как часто</th>'
                 '<th class="r">кумулятивно</th></tr>' + tr
                 + '</table></div>' + tie_note + '</section>')

    if tot:
        rowsw = []
        allp = [p for w in d["writing"] for p in w["parts"]]
        allp.sort(key=lambda p: -p["n"])
        mxp = max(p["n"] for p in allp)
        for p in allp:
            rowsw.append((p["form"], p["n"] / mxp * 100,
                          num(p["n"], 0) + "  \u00b7  " + p["kind"], KIND_CLS[p["kind"]]))
        segs, leg = [], []
        for k in KINDS:
            if not d["wr"][k]:
                continue
            sh = 100.0 * d["wr"][k] / tot
            segs.append('<div class="' + KIND_CLS[k] + '" style="width:'
                        + ("%.4f" % max(sh, 0.001)) + '%" title="' + esc(k) + " "
                        + num(sh, 1) + ' %">'
                        + (esc(k) + " " + num(sh, 1) + " %" if sh >= 14 else "")
                        + '</div>')
            leg.append('<span><i style="background:var(--' + KIND_VAR[k] + ')"></i>'
                       + esc(k) + " " + num(d["wr"][k], 0)
                       + " (" + num(sh, 1) + ' %)</span>')
        if len(d["cores"]) > 1:
            tail = ("\u0417\u043d\u0430\u043a\u0430\u043c\u0438 \u0441\u043b\u043e\u0432\u043e \u043f\u0438\u0448\u0435\u0442\u0441\u044f \u043f\u043e-\u0440\u0430\u0437\u043d\u043e\u043c\u0443: "
                    + ", ".join('<span class="jp">' + esc(c) + "</span> " + num(n, 0)
                                for c, n in d["cores"])
                    + " \u2014 \u0432 \u043e\u0434\u043d\u0443 \u0434\u043e\u043b\u044e \u043e\u043d\u0438 \u0441\u043b\u043e\u0436\u0435\u043d\u044b, \u043d\u043e \u044d\u0442\u043e \u0440\u0430\u0437\u043d\u044b\u0435 \u043d\u0430\u0447\u0435\u0440\u0442\u0430\u043d\u0438\u044f.")
        elif len(allp) > 1:
            tail = ("\u0412\u0441\u0435 \u0441\u0442\u0440\u043e\u043a\u0438 \u0437\u0434\u0435\u0441\u044c \u2014 \u043e\u0434\u043d\u043e \u0438 \u0442\u043e \u0436\u0435 \u0441\u043b\u043e\u0432\u043e \u0432 \u0440\u0430\u0437\u043d\u043e\u0439 \u0437\u0430\u043f\u0438\u0441\u0438: "
                    "\u0432\u0441\u0442\u0440\u0435\u0442\u0438\u0432 \u043b\u044e\u0431\u043e\u0435 \u0438\u0437 \u044d\u0442\u0438\u0445 \u043d\u0430\u043f\u0438\u0441\u0430\u043d\u0438\u0439, \u0442\u044b \u0447\u0438\u0442\u0430\u0435\u0448\u044c \u0442\u0443 \u0436\u0435 \u043b\u0435\u043c\u043c\u0443.")
        else:
            tail = "\u0420\u0430\u0437\u043d\u043e\u0447\u0442\u0435\u043d\u0438\u0439 \u0432 \u0437\u0430\u043f\u0438\u0441\u0438 \u0443 \u044d\u0442\u043e\u0433\u043e \u0441\u043b\u043e\u0432\u0430 \u043d\u0435\u0442."
        parts.append(
            '<section class="card"><h2>\u0417\u0430\u043f\u0438\u0441\u044c: \u0447\u0435\u043c \u0441\u043b\u043e\u0432\u043e \u043d\u0430\u0431\u0440\u0430\u043d\u043e</h2>'
            + '<div class="split">' + "".join(segs) + '</div>'
            + '<div class="legend">' + "".join(leg) + '</div>'
            + bar_rows(rowsw[:12])
            + ('<details><summary>\u043f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0432\u0441\u0435 \u043d\u0430\u043f\u0438\u0441\u0430\u043d\u0438\u044f: ' + str(len(allp)) + '</summary>'
               + bar_rows(rowsw[12:]) + '</details>' if len(allp) > 12 else "")
            + '<p class="note">' + script_note(d).capitalize() + ". " + tail
            + '</p></section>')

    if d["ratio"]:
        inside = 100.0 * (d["freq_s"] - d["freq_l"]) / d["freq_s"]
        if d["ratio"] < 1.1:
            said = ('Внутрь более длинных слов уходит ' + num(inside, 1)
                    + ' % вхождений — почти ничего. Единицу можно учить как отдельное '
                      'слово: сложений она практически не образует.')
        elif d["ratio"] < 2:
            said = ('Внутрь более длинных слов уходит ' + num(inside, 1)
                    + ' % вхождений. Слово самостоятельное, но заметная часть встреч '
                      'придётся на составные — их стоит знать.')
        else:
            said = ('Самостоятельным словом идёт лишь ' + num(100 / d["ratio"], 0)
                    + ' % вхождений: остальное — внутри более длинных слов. Это скорее '
                      'морфема, и учить её осмысленно в составе, а не отдельно.')
        # Числа берутся из двух разных таблиц, и это надо называть: 12 511 —
        # частота короткой единицы (suw), 3 578 — частота слова целиком (luw2).
        # Сравниваются абсолютные частоты: pmw у двух баз считаются от разных
        # знаменателей токенов и напрямую несравнимы.
        parts.append('<section class="card"><h2>Слово или морфема</h2>'
                     '<p class="note">Короткой единицей (SUW) слово встречается <b>'
                     + num(d["freq_s"], 0) + '</b> раз, самостоятельным словом (LUW2) — '
                     '<b>' + num(d["freq_l"], 0) + '</b>. ' + said + '</p></section>')

    # Составные идут сразу под «Словом или морфемой»: там сказано, что 71 %
    # вхождений уходит внутрь других единиц, а здесь видно, внутрь каких
    # именно. Само слово стоит в том же списке — иначе массу составных
    # не с чем сравнить; знаменатель у всех строк один, pmw LUW2.
    if d["inner"]:
        me = {"word": d["word"], "pmw": d["pmw"], "freq": d["freq_l"], "self": True}
        items = sorted(d["inner"] + [me], key=lambda s: -s["pmw"])
        mxi = max(s["pmw"] for s in items) or 1.0

        def irow(s):
            return (s["word"], s["pmw"] / mxi * 100,
                    num(s["pmw"]) + " pmw  \u00b7  freq " + num(s["freq"], 0),
                    bool(s.get("self")))

        si = next(i for i, s in enumerate(items) if s.get("self"))
        top, tail_i = items[:10], items[10:]
        if si >= 10:
            # строка самого слова нужна на виду всегда: она — точка отсчёта
            top = top + [items[si]]
            tail_i = [s for i, s in enumerate(items) if i >= 10 and i != si]

        m = d["inner_mass"]
        share = 100 * m / (m + d["pmw"]) if d["pmw"] else 100.0
        rest = ""
        if tail_i:
            rest = ('<details><summary>показать все ' + str(len(d["inner"])) + ' '
                    + plural(len(d["inner"]), "составную единицу",
                             "составные единицы", "составных единиц") + '</summary>'
                    + bar_rows([irow(s) for s in tail_i], hi=d["word"])
                    + '</details>')
        recon = ""
        inside_f = d["freq_s"] - d["freq_l"] if d["ratio"] else 0
        if inside_f > 0:
            gap = inside_f - d["inner_freq"]
            if not gap:
                recon = ('<p class="note">Внутрь составных уходит '
                         + num(inside_f, 0) + ' вхождений — ровно столько же '
                         'набирают единицы в списке.</p>')
            else:
                recon = ('<p class="note">Внутрь составных уходит <b>'
                         + num(inside_f, 0) + '</b> вхождений по разметке SUW, '
                         'а единицы списка набирают <b>' + num(d["inner_freq"], 0)
                         + '</b>: разошлось ' + num(abs(gap), 0) + ' ('
                         + num(100.0 * abs(gap) / inside_f, 1) + ' %). Сходиться '
                         'точно они и не должны: в luw2 нет единиц с частотой 1, '
                         'а SUW и LUW2 режут текст по-разному.</p>')
        parts.append('<section class="card"><h2>Входит в состав других единиц LUW2</h2>'
                     + bar_rows([irow(s) for s in top], hi=d["word"])
                     + '<p class="note">Само слово стоит в списке для сравнения: '
                     '<b class="jp">' + esc(d["word"]) + '</b> отдельным словом '
                     'весит ' + num(d["pmw"]) + ' pmw, а ' + str(len(d["inner"])) + ' '
                     + plural(len(d["inner"]), "составная единица", "составные единицы",
                              "составных единиц") + ' — ' + num(m)
                     + ' pmw вместе. На составные приходится <b>' + num(share, 1)
                     + ' %</b> совокупной массы.</p>' + recon + rest + '</section>')
    else:
        parts.append('<section class="card"><h2>Входит в состав других единиц LUW2</h2>'
                     '<p class="note">Ни в одну составную единицу не входит — здесь '
                     'ищется только вхождение леммы целиком.</p></section>')

    # ---- жанры. Разметочные таблицы LUW2/SUW убраны: их числа уже есть
    # в метриках и в разделе «Слово или морфема». Осталось то, чего больше
    # нигде нет, — где слово водится.
    src = d["luw"] or d["suw"]
    if src:
        u = src[0]
        regs, base = u["regs"], u["pmw"]
        present = sorted(((c, v) for c, v in regs.items() if v > 0), key=lambda x: -x[1])
        absent = [REGISTERS[c] for c in REGISTERS if regs.get(c, 0.0) <= 0]

        said_g = ""
        if present:
            c0, v0 = present[0]
            k = v0 / base if base else 0.0
            if k >= 1.5:
                said_g = ('Плотнее всего — ' + esc(REGISTERS[c0]) + ': ' + num(v0, 1)
                          + ' pmw против ' + num(base, 1) + ' по корпусу, то есть в '
                          + num(k, 1) + ' раза гуще среднего.')
            else:
                said_g = ('Слово распределено ровно: даже в самом плотном жанре ('
                          + esc(REGISTERS[c0]) + ') оно всего в ' + num(k, 1)
                          + ' раза гуще среднего по корпусу.')
            fams = [GROUP_OF[c] for c, _ in present[:3] if c in GROUP_OF]
            if len(set(fams)) == 1:
                said_g += (' Вся тройка лидеров — из семьи «' + fams[0]
                           + '»: сфера у слова одна.')
        if absent:
            said_g += (' Совсем не встречается: ' + ", ".join(absent) + '.')
        else:
            said_g += ' Есть во всех тринадцати жанрах.'

        parts.append('<section class="card"><h2>В каких жанрах встречается</h2>'
                     + genre_rows(regs, base)
                     + '<p class="note">' + said_g + '</p>'
                     '<p class="note">Вертикальная риска на каждой дорожке — средняя '
                     'плотность слова по корпусу (' + num(base, 1) + ' pmw). Столбик '
                     'правее риски значит, что в этом жанре слово идёт гуще обычного, '
                     'левее — реже; «×» показывает во сколько раз.</p></section>')

    if d["same"]:
        tr = "".join('<tr><td class="jp">' + esc(s["reading"]) + '</td><td class="jp">'
                     + esc(s["word"]) + '</td><td class="r">' + num(s["pmw"])
                     + '</td><td>' + esc(s["pos"]) + '</td></tr>' for s in d["same"][:12])
        parts.append('<section class="card"><h2>Другие слова с тем же чтением</h2>'
                     '<div class="scroll"><table><tr><th>чтение</th><th>слово</th>'
                     '<th class="r">pmw</th><th>разметка</th></tr>' + tr
                     + '</table></div><p class="note">Читаются одинаково, но это другие '
                     'слова с другими значениями — на слух они неразличимы.</p>'
                     '</section>')

    parts.append(glossary(TERMS_WORD + TERMS_COMMON))
    return page(d["word"] + " — частотность BCCWJ", "\n".join(parts))


# ------------------------------------------------------- проверка данных
# Таблицы выведены из корпуса и в сессии не правятся. Тихий дрейф данных
# ничем себя не выдаёт — вердикт останется правдоподобным, — поэтому число
# строк сверяется с зашитыми константами. Расхождение = данные не те.
CHECKS = [("kanji", KANJI_TOTAL), ("luw2", LUW2_TOTAL), ("suw", SUW_TOTAL)]


def check() -> int:
    bad = 0
    for name, expected in CHECKS:
        got = sum(1 for _ in rows(name))
        ok = got == expected
        bad += not ok
        print(f"  {name:<8} {got:>7} строк, ожидалось {expected:>7}   "
              f"{'ок' if ok else 'РАСХОЖДЕНИЕ'}")
        print(f"  {'':8} {where(name)}")
    got = sum(1 for _ in rows("writing"))
    print(f"  {'writing':<8} {got:>7} строк, точное число не фиксируется")
    print(f"  {'':8} {where('writing')}")
    print("\nданные в порядке" if not bad else
          f"\nСБОЙ: не сошлось таблиц — {bad}. Пересобери базу через build_data.py "
          "на исходном корпусе и залей заново.")
    return bad


# ------------------------------------------------------------------ вход
# ============================================================ сравнение слов
def collect_table(words: list) -> dict:
    """Данные для сравнительной таблицы. Три прохода по данным на весь список,
    а не по три на каждое слово: collect_word читает luw2 дважды и годится
    для одного запроса, для десяти это десять полных чтений корпуса."""
    wanted, seen = [], set()
    for w in words:
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            wanted.append(w)

    luw = {w: [] for w in wanted}
    suw = {w: [] for w in wanted}
    for s in rows("luw2"):
        if s[2] in seen:
            luw[s[2]].append(s)
    for s in rows("suw"):
        if s[2] in seen:
            suw[s[2]].append(s)

    # ненайденным словам сразу ищем лемму по написаниям — в том же проходе,
    # что и раскладку записи, чтобы не читать таблицу написаний дважды
    missing = [w for w in wanted if not luw[w] and not suw[w]]
    wr = {w: {k: 0 for k in KINDS} for w in wanted}
    hits = {w: [] for w in missing}
    for s in rows("writing"):
        if s[1] in seen:
            tot, _ = script_split(s[6])
            for k in KINDS:
                wr[s[1]][k] += tot[k]
        if missing:
            forms = [x.rsplit("(", 1)[0].strip() for x in s[6].split(",")]
            for w in missing:
                if w in forms:
                    hits[w].append((int(s[4]), s[1]))

    items = []
    for w in wanted:
        L, S = luw[w], suw[w]
        if not L and not S:
            top = sorted(hits[w], reverse=True)[:3]
            items.append({"word": w, "found": False,
                          "hits": [{"lemma": lm, "n": n} for n, lm in top]})
            continue
        base = max(L or S, key=lambda x: float(x[6]))
        pmw = sum(float(x[6]) for x in L)
        freq_l = sum(int(x[5]) for x in L)
        freq_s = sum(int(x[5]) for x in S)
        band, label, note = verdict(pmw, WORD_BANDS, WORD_TAIL, ascending=False)
        kanji, kana = wr[w]["кандзи"], wr[w]["хирагана"] + wr[w]["катакана"]
        items.append({
            "word": w, "found": True, "reading": base[1], "pos": base[3],
            "rank": min(int(x[0]) for x in L) if L else None,
            "pmw": pmw, "freq_l": freq_l, "freq_s": freq_s,
            "band": band, "label": label, "note": note,
            "ratio": (freq_s / freq_l) if (L and S) else None,
            "kanji": kanji, "kana": kana, "other": wr[w]["прочее"],
            "wtot": sum(wr[w].values()),
        })

    # порядок — по частоте: таблица отвечает на вопрос «что раньше», а не
    # «в каком порядке я их выписал»
    items.sort(key=lambda x: (not x["found"], -(x.get("pmw") or 0.0)))
    return {"kind": "table", "items": items, "luw2_total": LUW2_TOTAL}


def ratio_short(k) -> str:
    """Короткая расшифровка SUW/LUW2 для ячейки таблицы."""
    if k is None:
        return "—"
    if k < 1.1:
        return "сама по себе"
    if k < 2:
        return "часть вхождений — внутри слов"
    return "живёт внутри других слов"


def script_short(d: dict) -> str:
    """Короткая расшифровка записи для ячейки таблицы."""
    tot = d["wtot"]
    if not tot:
        return "—"
    if not d["kanji"]:
        return "знака нет вовсе"
    share = 100.0 * d["kanji"] / tot
    if share >= 85:
        return "пишется знаком"
    if share >= 50:
        return "знаком чаще, но не всегда"
    return "в тексте чаще каной"


def table_note(items: list) -> str:
    """Вывод под таблицей — из чисел этого запроса, а не общих слов."""
    ok = [x for x in items if x["found"]]
    if not ok:
        return ""
    out = []
    bands = {}
    for x in ok:
        bands.setdefault(x["band"], []).append(x)
    top = max(bands.items(), key=lambda kv: len(kv[1]))
    if len(top[1]) > 1:
        out.append("В одной полосе «" + WORD_SHORT[top[0]] + "» — "
                   + num(len(top[1]), 0) + " "
                   + plural(len(top[1]), "слово", "слова", "слов") + " из "
                   + num(len(ok), 0) + ": "
                   + ", ".join(x["word"] for x in top[1])
                   + ". По частоте они неразличимы, выбирать между ними придётся "
                     "не по ней.")
    hi, lo = ok[0], ok[-1]
    if hi is not lo:
        out.append("Разброс — от " + hi["word"] + " (" + once_in(hi["pmw"], "слов")
                   + ") до " + lo["word"] + " (" + once_in(lo["pmw"], "слов")
                   + "): разница в " + num(hi["pmw"] / lo["pmw"], 0) + " раз.")
    kana = [x for x in ok if x["kanji"] and x["wtot"]
            and x["kanji"] / x["wtot"] < 0.5]
    if kana:
        out.append("В тексте чаще идут каной: "
                   + ", ".join(x["word"] + " (" + num(100.0 * x["kanji"] / x["wtot"], 0)
                               + " % знаком)" for x in kana)
                   + " — знак учить незачем, слово узнавать надо.")
    inner = [x for x in ok if x["ratio"] and x["ratio"] >= 2]
    if inner:
        out.append("Внутри других слов живут: "
                   + ", ".join(x["word"] + " (" + num(x["ratio"], 1) + "×)"
                               for x in inner)
                   + " — самостоятельным словом попадаются заметно реже.")
    return " ".join(out)


def strip_marks(segments, marks, left_end, right_end, ticks=()):
    """Полоса с несколькими метками сразу. Подписи разводятся по ярусам:
    у десяти слов из одной полосы позиции отличаются на проценты, и в один
    ряд они наезжают друг на друга."""
    ROW = 19
    lay, level_right = [], []
    for pos, label in sorted(marks, key=lambda m: m[0]):
        pos = min(max(pos, 0.0), 100.0)
        half = len(label) * 0.85 + 1.2      # полуширина подписи в % ширины полосы
        for i, right in enumerate(level_right):
            if pos - half > right:
                level_right[i] = pos + half
                lay.append((pos, label, i))
                break
        else:
            level_right.append(pos + half)
            lay.append((pos, label, len(level_right) - 1))
    total = max(len(level_right), 1)
    pad = (total - 1) * ROW + 26

    # Сначала все черты, потом все подписи: черта верхнего яруса проходит мимо
    # подписи нижнего, и подпись должна её перекрыть, а не наоборот.
    mk = "".join(
        f'<span class="pin mpin" style="left:{p:.2f}%;'
        f'top:{(total - 1 - lv) * ROW + 18}px;height:{lv * ROW + 14}px"></span>'
        for p, t, lv in lay)
    mk += "".join(
        f'<span class="lbl mlbl jp" style="left:{p:.2f}%;'
        f'top:{(total - 1 - lv) * ROW}px">{esc(t)}</span>'
        for p, t, lv in lay)
    segs = "".join(
        f'<div class="seg" style="width:{w:.4f}%;background:var(--{c})">'
        f'{esc(t) if w >= 9 else ""}</div>' for w, t, c in segments)
    # засечки стоят под полосой, а полоса съехала вниз на ярусы подписей
    tk = "".join(
        f'<div class="tick" style="left:{min(max(x, 0.0), 100.0):.2f}%;'
        f'top:{pad + 26}px"><i></i><span>{esc(t)}</span></div>' for x, t in ticks)
    return (f'<div class="strip" style="padding-top:{pad}px">{mk}'
            f'<div class="segs">{segs}</div>{tk}'
            f'<div class="ends"><span>{esc(left_end)}</span>'
            f'<span>{esc(right_end)}</span></div></div>')


def html_table(d: dict) -> str:
    items = d["items"]
    ok = [x for x in items if x["found"]]
    segs = [(20.0, WORD_SHORT[i], "b%d" % i) for i in range(5)]

    head_html = ('<div class="hero"><div class="hero-body">'
                 '<h1 class="tt">Сравнение: ' + num(len(items), 0) + ' '
                 + plural(len(items), "слово", "слова", "слов") + '</h1>'
                 '<p class="lead">Одна строка — одно слово: как часто попадается, '
                 'где стоит в списке LUW2, каким письмом идёт в тексте и стоит ли '
                 'самостоятельно. Полная справка по каждому — '
                 '<b>python freq.py &lt;слово&gt;</b>.</p></div></div>')

    scale = ""
    if ok:
        scale = ('<section class="card"><h2>Место на шкале частот</h2>'
                 + strip_marks(segs, [(word_pos(x["pmw"]), x["word"]) for x in ok],
                               "раз на " + per_words(WORD_SCALE_HI) + " слов",
                               "раз на " + per_words(WORD_SCALE_LO) + " слов",
                               ticks=[(word_pos(b[0]), per_words(b[0]))
                                      for b in WORD_BANDS])
                 + '</section>')

    tr = []
    for x in items:
        if not x["found"]:
            tip = "нет такой леммы в корпусе"
            if x["hits"]:
                tip = ("написание принадлежит другим леммам: "
                       + ", ".join(h["lemma"] for h in x["hits"]))
            tr.append('<tr class="off"><td class="jp w">' + esc(x["word"])
                      + '</td><td colspan="5">' + esc(tip) + '</td></tr>')
            continue
        share = (num(100.0 * x["kanji"] / x["wtot"], 0) + " %"
                 if x["wtot"] and x["kanji"] else "—")
        tr.append(
            '<tr><td class="jp w">' + esc(x["word"])
            + '<span class="sub jp">' + esc(x["reading"]) + ' · '
            + esc(x["pos"].split("-")[0]) + '</span></td>'
            '<td><span class="badge b' + str(x["band"]) + '">' + esc(x["label"])
            + '</span></td>'
            '<td class="r">' + once_in(x["pmw"], "слов")
            + '<span class="sub">' + num(x["pmw"]) + ' pmw</span></td>'
            '<td class="r">' + (num(x["rank"], 0) if x["rank"] else "—")
            + '<span class="sub">из ' + num(d["luw2_total"], 0) + '</span></td>'
            '<td class="r">' + share
            + '<span class="sub">' + esc(script_short(x)) + '</span></td>'
            '<td class="r">' + (num(x["ratio"], 2) + "×" if x["ratio"] else "—")
            + '<span class="sub">' + esc(ratio_short(x["ratio"])) + '</span></td></tr>')

    note = table_note(items)
    table = ('<section class="card"><h2>Слова по убыванию частоты</h2>'
             '<div class="scroll"><table class="cmp"><tr><th>слово</th>'
             '<th>вердикт</th><th class="r">как часто</th><th class="r">ранг LUW2</th>'
             '<th class="r">знаком</th><th class="r">SUW / LUW2</th></tr>'
             + "".join(tr) + '</table></div>'
             + ('<p class="note">' + note + '</p>' if note else "")
             + '</section>')

    terms = [("как часто", "во сколько слов текста укладывается одна встреча: "
              "<b>10⁶ / pmw</b> по LUW2."),
             ("ранг LUW2", "место среди " + num(d["luw2_total"], 0)
              + " разных слов корпуса; ранги в хвосте слипаются, поэтому вердикт "
                "берётся от частоты, а не от ранга."),
             ("знаком", "доля вхождений, записанных иероглифом, против каны: "
              "слово может быть частотным, а знак в нём — почти невидимым."),
             ("SUW / LUW2", "во сколько раз единица встречается чаще, чем стоит "
              "самостоятельным словом. 1,0× — самостоятельное слово, 7× — морфема "
              "внутри других слов.")]
    return page("Сравнение: " + " · ".join(x["word"] for x in items),
                head_html + scale + table + glossary(terms))


def render_text_table(d: dict):
    head("СРАВНЕНИЕ " + str(len(d["items"])) + " СЛОВ")
    print(f'  {pad("слово", 12)}{pad("вердикт", 15)}{pad("как часто", 26)}'
          f'{pad("ранг", 9)}{pad("знаком", 9)}SUW/LUW2')
    for x in d["items"]:
        if not x["found"]:
            print(f'  {pad(x["word"], 12)}не найдено'
                  + (" — есть леммы: " + ", ".join(h["lemma"] for h in x["hits"])
                     if x["hits"] else ""))
            continue
        share = (num(100.0 * x["kanji"] / x["wtot"], 0) + " %"
                 if x["wtot"] and x["kanji"] else "—")
        print(f'  {pad(x["word"], 12)}{pad(x["label"], 15)}'
              f'{pad(once_in(x["pmw"], "слов"), 26)}'
              f'{pad(num(x["rank"], 0) if x["rank"] else "—", 9)}{pad(share, 9)}'
              + (num(x["ratio"], 2) + "×" if x["ratio"] else "—"))
    note = table_note(d["items"])
    if note:
        print()
        for line in note.split(". "):
            if line.strip():
                print("  " + line.strip().rstrip(".") + ".")


USAGE = ("укажи кандзи или слово:  python freq.py 浸かる\n"
         "несколько слов -> таблица: python freq.py 扉 唾 引き戸\n"
         "страницей вместо текста: python freq.py --html 浸かる\n"
         "проверка данных:         python freq.py --check")


def out_path(query: str, given: str | None) -> str:
    if given:
        d = os.path.dirname(os.path.abspath(given))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        return os.path.abspath(given)
    base = os.environ.get("JP_FREQ_OUT") or os.path.join(HERE, "out")
    os.makedirs(base, exist_ok=True)
    safe = "".join(c for c in query if c not in '\\/:*?"<>|').strip() or "freq"
    return os.path.join(base, safe + ".html")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    as_html, target = False, None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--html":
            as_html = True
        elif a in ("-o", "--out"):
            i += 1
            target = args[i] if i < len(args) else None
        else:
            rest.append(a)
        i += 1

    if not rest:
        sys.exit(USAGE)
    q = rest[0].strip()

    if q == "--check":
        head("ПРОВЕРКА ДАННЫХ")
        sys.exit(1 if check() else 0)

    if len(rest) > 1:
        # третий тип выдачи: список слов -> сравнительная таблица
        data = collect_table(rest)
        render_text, render_html = render_text_table, html_table
        q = "сравнение " + "-".join(rest[:4]) + ("" if len(rest) <= 4 else "-и-ещё")
    elif len(q) == 1 and is_kanji(q):
        data = collect_kanji(q)
        render_text, render_html = render_text_kanji, html_kanji
    else:
        data = collect_word(q)
        render_text, render_html = render_text_word, html_word

    if as_html:
        path = out_path(q, target)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_html(data))
        print(path)
    else:
        render_text(data)
        print()


if __name__ == "__main__":
    main()
