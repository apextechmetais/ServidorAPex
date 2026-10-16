"""Utilidades compartilhadas: data/hora de São Paulo e formatação."""
from datetime import datetime, date

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem base de fusos: usa UTC-3 fixo (o Brasil não tem mais horário de verão)
    from datetime import timezone, timedelta
    FUSO = timezone(timedelta(hours=-3))


def agora_sp():
    return datetime.now(FUSO)


def hoje_sp():
    """Data de hoje em São Paulo (o servidor roda em UTC: depois das 21h já seria o dia seguinte)."""
    return agora_sp().date()


def somar_meses(d: date, meses: int) -> date:
    """Mesma data N meses depois; dia 31 em mês curto vira o último dia do mês."""
    import calendar
    ano = d.year + (d.month - 1 + meses) // 12
    mes = (d.month - 1 + meses) % 12 + 1
    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def brl(valor):
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{abs(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if numero < 0 else "R$ ") + texto
