"""Conversão de períodos em linguagem natural para intervalos de data."""
from datetime import date, timedelta


def resolve_period(periodo: str | None):
    """Retorna (data_inicio, data_fim, rotulo) em ISO 'YYYY-MM-DD'.

    Aceita: hoje, ontem, semana, semana_passada, mes, mes_passado,
    bimestre, ano, tudo. Default = mês atual.
    """
    hoje = date.today()
    p = (periodo or "mes").strip().lower()

    if p in ("hoje", "dia"):
        return hoje.isoformat(), hoje.isoformat(), "hoje"

    if p == "ontem":
        o = hoje - timedelta(days=1)
        return o.isoformat(), o.isoformat(), "ontem"

    if p in ("semana", "esta_semana"):
        inicio = hoje - timedelta(days=hoje.weekday())  # segunda
        return inicio.isoformat(), hoje.isoformat(), "esta semana"

    if p in ("semana_passada", "ultima_semana"):
        inicio_atual = hoje - timedelta(days=hoje.weekday())
        inicio = inicio_atual - timedelta(days=7)
        fim = inicio_atual - timedelta(days=1)
        return inicio.isoformat(), fim.isoformat(), "semana passada"

    if p in ("mes", "este_mes", "mensal"):
        inicio = hoje.replace(day=1)
        return inicio.isoformat(), hoje.isoformat(), "este mês"

    if p in ("mes_passado", "ultimo_mes"):
        primeiro_deste = hoje.replace(day=1)
        fim = primeiro_deste - timedelta(days=1)
        inicio = fim.replace(day=1)
        return inicio.isoformat(), fim.isoformat(), "mês passado"

    if p in ("bimestre", "comparativo"):
        primeiro_deste = hoje.replace(day=1)
        fim_passado = primeiro_deste - timedelta(days=1)
        inicio = fim_passado.replace(day=1)
        return inicio.isoformat(), hoje.isoformat(), "últimos 2 meses"

    if p in ("ano", "este_ano", "anual"):
        inicio = hoje.replace(month=1, day=1)
        return inicio.isoformat(), hoje.isoformat(), "este ano"

    if p in ("tudo", "todos", "geral", "all"):
        return None, None, "todo o período"

    # fallback
    inicio = hoje.replace(day=1)
    return inicio.isoformat(), hoje.isoformat(), "este mês"


def month_bounds(ref: date):
    """(primeiro_dia, ultimo_dia) do mês de `ref`."""
    primeiro = ref.replace(day=1)
    if ref.month == 12:
        proximo = ref.replace(year=ref.year + 1, month=1, day=1)
    else:
        proximo = ref.replace(month=ref.month + 1, day=1)
    ultimo = proximo - timedelta(days=1)
    return primeiro, ultimo
