"""PILAS — bot financeiro multiusuário no Telegram. Ponto de entrada.

Rode com:  python bot.py

Fluxo: cada chat passa primeiro pela camada de login (auth.py). Só mensagens
de um usuário logado seguem pro fluxo financeiro (fast-path local -> IA).
"""
import logging
import os
from collections import defaultdict, deque

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import agent
import auth
import config
import database
import fast

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("pilas")

# Histórico de conversa por (chat, usuário): últimas ~10 trocas, só texto.
_HISTORICO: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=20))


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Limpa só a memória de conversa do usuário logado neste chat."""
    chat_id = update.effective_chat.id
    user = auth.current_user(chat_id)
    if user:
        _HISTORICO.pop((chat_id, user["id"]), None)
        await update.message.reply_text("Memória da conversa limpa. ✅")
    else:
        await update.message.reply_text("Você não tá logado. Manda um 'oi'. 🐷")


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    texto = update.message.text

    # 1) Camada de login/cadastro
    res = auth.handle(chat_id, texto)
    if res["reply"]:
        await update.message.reply_text(res["reply"])
    if not res["passthrough"]:
        return

    user = res["user"]
    hist = _HISTORICO[(chat_id, user["id"])]

    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2) Fast-path local (sem IA) -> 3) IA como fallback
    graficos = []
    try:
        local = fast.try_handle(texto, user["id"]) if config.FAST_PATH else None
        if local is not None:
            resposta, graficos = local["texto"], local["charts"]
            log.info("fast-path resolveu (sem IA) p/ user %s", user["id"])
        else:
            resposta, graficos, _ = await agent.responder(
                list(hist), texto, user["id"], user["nome"]
            )
    except Exception as e:
        # IA indisponível (limite) ou erro: responde com dica amigável, sem assustar
        log.warning("IA indisponível/erro, usando dica local: %s", e)
        await update.message.reply_text(fast.NUDGE)
        return

    hist.append({"role": "user", "content": texto})
    hist.append({"role": "assistant", "content": resposta})

    if resposta:
        await update.message.reply_text(resposta)

    for caminho in graficos:
        try:
            with open(caminho, "rb") as img:
                await ctx.bot.send_photo(chat_id=chat_id, photo=img)
        except Exception:
            log.exception("Falha ao enviar gráfico %s", caminho)
        finally:
            # gráfico já foi enviado; remove pra não acumular no disco
            try:
                os.remove(caminho)
            except OSError:
                pass


def main():
    config.validate()
    database.init_db()

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("reset", cmd_reset))
    # /start /login /sair /cadastrar passam pelo mesmo handler (vão pro auth)
    app.add_handler(CommandHandler(["start", "login", "sair", "cadastrar"], on_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("PILAS no ar (multiusuário). 🐷 Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
