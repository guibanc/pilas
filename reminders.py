"""Lembretes automáticos do PILAS (fim do dia, semanal, cofrinho).

Usa o JobQueue do python-telegram-bot. Um "tick" roda de hora em hora e, pra
cada usuário, dispara o que estiver configurado pra aquele horário/dia.
Os lembretes vão pro(s) chat(s) onde o usuário está logado.
"""
import logging
import os
from datetime import datetime

import charts
import config
import database
from tools import ToolExecutor, _fmt

log = logging.getLogger("pilas.reminders")


# ----------------------------- textos -----------------------------

def texto_diario(user_id) -> str:
    hoje = datetime.now(config.TZ).date().isoformat()
    txs = database.query_transactions(user_id, hoje, hoje, tipo="gasto")
    if not txs:
        return "Fechando o dia 🐷 Hoje você não registrou nenhum gasto. Mandou bem! 👏"
    total = sum(t["valor"] for t in txs)
    maior = max(txs, key=lambda t: t["valor"])
    return (
        f"Fechando o dia 🐷 Hoje foram {_fmt(total)} em {len(txs)} lançamento(s).\n"
        f"Maior: {_fmt(maior['valor'])} em {maior['categoria']}."
    )


def texto_e_pdf_semanal(user_id):
    """Retorna (texto, caminho_pdf|None)."""
    ex = ToolExecutor(user_id)
    resumo = ex.run("get_summary", {"periodo": "semana"})
    nome = (database.get_user(user_id) or {}).get("nome", "")
    pdf, _ = charts.dashboard_pdf(user_id, "semana", nome)
    return "📊 Seu relatório da semana:\n" + resumo, pdf


def texto_cofrinho(user_id) -> str:
    s = database.get_savings(user_id)
    if s["meta"] and s["meta"] > 0:
        falta = max(0.0, s["meta"] - s["total"])
        pct = min(100, s["total"] / s["meta"] * 100)
        if falta <= 0:
            return f"🐖 Cofrinho no talo! Você bateu a meta de {_fmt(s['meta'])}. 🎉"
        return (
            f"🐖 Lembrete do cofrinho! Você já guardou {_fmt(s['total'])} de "
            f"{_fmt(s['meta'])} ({pct:.0f}%). Faltam {_fmt(falta)}.\n"
            "Bora separar um pouco hoje? Manda \"guardar 50 no cofrinho\"."
        )
    return ("🐖 Que tal começar um cofrinho? Define uma meta assim: "
            "\"meta do cofrinho 1000\" — eu te lembro de guardar. 😉")


# ----------------------------- envio -----------------------------

async def _enviar(bot, chats, texto, pdf=None):
    for chat_id in chats:
        try:
            await bot.send_message(chat_id=chat_id, text=texto)
            if pdf:
                with open(pdf, "rb") as f:
                    await bot.send_document(chat_id=chat_id, document=f)
        except Exception:
            log.exception("Falha ao enviar lembrete pro chat %s", chat_id)
    if pdf:
        try:
            os.remove(pdf)
        except OSError:
            pass


async def tick(context):
    """Roda de hora em hora; dispara os lembretes do horário/dia atual."""
    now = datetime.now(config.TZ)
    hoje = now.date().isoformat()
    semana = f"{now.isocalendar().year}-{now.isocalendar().week}"
    bot = context.bot

    for uid in database.all_user_ids():
        chats = database.get_chats_for_user(uid)
        if not chats:
            continue  # ninguém logado nesse usuário -> não há onde mandar
        p = database.get_prefs(uid)

        # fim do dia
        if p["daily"] and now.hour == p["daily_hour"] and p["last_daily"] != hoje:
            await _enviar(bot, chats, texto_diario(uid))
            database.set_pref(uid, "last_daily", hoje)

        # semanal
        if (p["weekly"] and now.weekday() == p["weekly_day"]
                and now.hour == p["weekly_hour"] and p["last_weekly"] != semana):
            txt, pdf = texto_e_pdf_semanal(uid)
            await _enviar(bot, chats, txt, pdf)
            database.set_pref(uid, "last_weekly", semana)

        # cofrinho
        if (p["cofrinho"] and now.weekday() == p["cof_day"]
                and now.hour == p["cof_hour"] and p["last_cof"] != hoje):
            await _enviar(bot, chats, texto_cofrinho(uid))
            database.set_pref(uid, "last_cof", hoje)


def setup(application):
    """Agenda o tick de hora em hora. Chamar no main() do bot."""
    jq = getattr(application, "job_queue", None)
    if jq is None:
        log.warning("JobQueue indisponível — lembretes desligados. "
                    "Instale: pip install 'python-telegram-bot[job-queue]'")
        return
    jq.run_repeating(tick, interval=3600, first=30)
    log.info("Lembretes agendados (tick de hora em hora, fuso %s).", config.TZ)
