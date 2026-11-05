import calendar
from datetime import date, datetime, timedelta, timezone
import re


MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

NUMBER_WORDS = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


BUSINESS_TZ = timezone(timedelta(hours=-4))


def normalizar(text: str) -> str:
    accents = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u",
        "ü": "u", "Ü": "u",
    }
    cleaned = "".join(accents.get(ch, ch) for ch in text.lower())
    return " " + cleaned + " "


def nombrado(nombre: str, texto: str) -> bool:
    norm_nombre = normalizar(nombre).strip()
    norm_texto = normalizar(texto)
    return bool(re.search(r'(?<!\w)' + re.escape(norm_nombre) + r'(?!\w)', norm_texto))


def extraer_periodo(text: str, hoy: date | None = None) -> tuple[tuple[date, date] | None, str]:
    today = hoy or datetime.now(BUSINESS_TZ).date()
    norm = normalizar(text)

    # 1. Fechas explícitas YYYY-MM-DD o DD/MM/YYYY
    dates = re.findall(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b', text)
    if dates:
        if len(dates) > 2:
            raise ValueError('Indicá como máximo una fecha inicial y una final.')
        parsed = []
        for val in dates:
            try:
                parsed.append(datetime.strptime(val, '%Y-%m-%d' if '-' in val else '%d/%m/%Y').date())
            except ValueError:
                raise ValueError('La fecha no es válida. Usá DD/MM/AAAA o AAAA-MM-DD.')
        first, last = parsed[0], parsed[-1]
        if first > last:
            raise ValueError('La fecha inicial no puede ser posterior a la final.')
        return (first, last), 'explicit'

    # 2. Mes específico por nombre (ej: "septiembre", "en agosto")
    for m_name, m_num in MONTHS_ES.items():
        if re.search(r'\b' + m_name + r'\b', norm):
            year = today.year
            # Si el mes es futuro respecto al actual, o si se especifica año
            year_match = re.search(r'\b(202\d)\b', text)
            if year_match:
                year = int(year_match.group(1))
            _, last_day = calendar.monthrange(year, m_num)
            return (date(year, m_num, 1), date(year, m_num, last_day)), f"mes_{m_name}"

    # 3. Expresiones relativas
    if re.search(r"\bhoy\b", norm):
        return (today, today), "today"

    if re.search(r"\bayer\b", norm):
        yesterday = today - timedelta(days=1)
        return (yesterday, yesterday), "yesterday"

    # "ultimos 3 meses", "ultimos tres meses", "ultimas 2 semanas"
    match = re.search(r"(?:ultimos?|ultimas?)\s+(\w+|\d+)\s+(dia|dias|semana|semanas|mes|meses)", norm)
    if match:
        val_str = match.group(1)
        value = int(val_str) if val_str.isdigit() else NUMBER_WORDS.get(val_str, 1)
        unit = match.group(2)
        if unit.startswith("mes"):
            # Últimos N meses
            days = value * 30
        elif unit.startswith("sema"):
            days = value * 7
        else:
            days = value
        if not 1 <= days <= 3660:
            raise ValueError('El período debe estar entre 1 día y 10 años.')
        start_date = today - timedelta(days=days - 1)
        return (start_date, today), "last_period"

    if re.search(r"mes actual|este mes", norm):
        return (today.replace(day=1), today), "month"

    if re.search(r"mes pasado|mes anterior|ultimo mes", norm):
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        return (first_of_prev_month, last_of_prev_month), "last_month"

    if re.search(r"ano actual|este ano|ano en curso|año", norm):
        return (today.replace(month=1, day=1), today), "year"

    return None, "none"
