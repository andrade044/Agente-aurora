"""Utilitários de texto em português: normalização, tokenização, datas e moeda."""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no",
    "na", "nos", "nas", "por", "para", "pra", "com", "sem", "e", "ou", "que", "qual", "quais",
    "se", "me", "meu", "minha", "eu", "voce", "ao", "aos", "como", "onde", "quando", "ser", "sao",
    "e", "esta", "este", "isso", "isto", "ha", "tem", "ter", "sobre", "mais", "menos", "muito",
    "pelo", "pela", "pelos", "pelas", "foi", "seu", "sua", "lhe", "nao", "sim", "existe", "algum",
    "alguma", "posso", "devo", "preciso", "fazer", "faco", "pedir", "peco", "gostaria", "saber",
}


def normalize(text: str) -> str:
    """Minúsculas e sem acentos."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9@._-]+", normalize(text))


def stem(token: str) -> str:
    """Radical grosseiro: remove plural simples e corta em 6 caracteres.

    Suficiente para um corpus pequeno (aprovação/aprovações → "aprova").
    """
    if len(token) > 4 and token.endswith("oes"):
        token = token[:-3] + "ao"
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token[:6]


def terms(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


# --------------------------------------------------------------------------- moeda

def brl(value: Decimal | float | int | None) -> str:
    if value is None:
        return "R$ 0,00"
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    inteiro, centavos = f"{abs(d):.2f}".split(".")
    inteiro = f"{int(inteiro):,}".replace(",", ".")
    return f"{sign}R$ {inteiro},{centavos}"


def pct(value: Decimal | float | None) -> str:
    if value is None:
        return "n/d"
    d = (Decimal(str(value)) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d}".replace(".", ",") + "%"


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural_ or singular + 's')}"


def br_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


# --------------------------------------------------------------------------- períodos

MONTHS = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "mar": 3, "abril": 4, "abr": 4,
    "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7, "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9, "outubro": 10, "out": 10, "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}
MONTH_NAMES = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho", 7: "julho",
               8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"}
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b")
_ORDINAL = {"primeiro": 1, "1o": 1, "1": 1, "segundo": 2, "2o": 2, "2": 2, "terceiro": 3,
            "3o": 3, "3": 3, "quarto": 4, "4o": 4, "4": 4}


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def label(self) -> str:
        """Rótulo legível: "janeiro de 2026", "2025", "janeiro a março de 2025" ou datas explícitas."""
        s, e = self.start, self.end
        if s.day == 1 and e == _month_end(e.year, e.month):
            if s.year == e.year:
                if s.month == 1 and e.month == 12:
                    return str(s.year)
                if s.month == e.month:
                    return f"{MONTH_NAMES[s.month]} de {s.year}"
                return f"{MONTH_NAMES[s.month]} a {MONTH_NAMES[e.month]} de {s.year}"
            return f"{MONTH_NAMES[s.month]} de {s.year} a {MONTH_NAMES[e.month]} de {e.year}"
        return f"{br_date(s)} a {br_date(e)}"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_period(text: str) -> Period | None:
    """Extrai um período de datas de uma pergunta em português.

    Suporta: "janeiro a março de 2025", "em jan/2026", "2025", "1º trimestre de 2025",
    "segundo semestre de 2026", "de 2025-01-01 a 2025-03-31", "03/2025".
    Retorna None se nenhum período for encontrado.
    """
    t = normalize(text).replace("º", "o").replace("°", "o")

    iso = re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if len(iso) >= 2:
        a, b = iso[0], iso[1]
        return Period(date(int(a[0]), int(a[1]), int(a[2])), date(int(b[0]), int(b[1]), int(b[2])))

    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", t)]

    # mm/aaaa
    mm_yyyy = re.findall(r"\b(0?[1-9]|1[0-2])/(20\d{2})\b", t)
    if mm_yyyy:
        first, last = mm_yyyy[0], mm_yyyy[-1]
        return Period(date(int(first[1]), int(first[0]), 1), _month_end(int(last[1]), int(last[0])))

    if not years:
        return None
    year = years[0]

    m = re.search(r"\b(primeiro|segundo|terceiro|quarto|[1-4]o?)\s+trimestre\b", t)
    if m:
        q = _ORDINAL[m.group(1)]
        return Period(date(year, 3 * q - 2, 1), _month_end(year, 3 * q))
    m = re.search(r"\b(primeiro|segundo|[12]o?)\s+semestre\b", t)
    if m:
        s = _ORDINAL[m.group(1)]
        return Period(date(year, 6 * s - 5, 1), _month_end(year, 6 * s))

    # "mar" e "set" também são palavras comuns; só valem como mês perto de um ano ou de outro mês
    months = [MONTHS[x] for x in _MONTH_RE.findall(t)]
    if months:
        if len(years) >= 2 and len(months) >= 2:
            return Period(date(years[0], months[0], 1), _month_end(years[-1], months[-1]))
        return Period(date(year, min(months[0], months[-1]), 1),
                      _month_end(year, max(months[0], months[-1])))

    if len(years) >= 2:
        return Period(date(min(years), 1, 1), date(max(years), 12, 31))
    return Period(date(year, 1, 1), date(year, 12, 31))
