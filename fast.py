"""Fast-path local do PILAS: resolve mensagens comuns SEM chamar a IA.

Padrões simples (registrar gasto/entrada, consultar, gráfico, limite, saudação)
são interpretados aqui com regex + palavras-chave. Só o que for ambíguo cai na IA.

`try_handle(mensagem, user_id)` retorna {"texto": str, "charts": [paths]} ou None.
None = "não sei resolver isso, manda pra IA".
"""
import random
import re
import unicodedata

import database
from tools import ToolExecutor, _fmt

# ----------------------------- normalização -----------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return _strip_accents(s.lower())


# ----------------------------- valor (R$) -----------------------------

def parse_valor(texto: str):
    """Extrai o primeiro valor do texto. Entende 45 / 45,90 / 1.200,50 / 2k / 3 mil.
    Retorna float ou None."""
    t = _norm(texto)
    m = re.search(
        r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(k|mil)?\b", t
    )
    if not m:
        return None
    s, suf = m.group(1), m.group(2)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d+\.\d{3}", s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    if suf in ("k", "mil"):
        v *= 1000
    return v if v > 0 else None


# ----------------------------- categorias -----------------------------
# Ordem importa: a 1ª categoria cujo keyword aparecer (palavra inteira) ganha.
_CAT_KEYWORDS = [
    ("assinaturas", ["assinaturas", "assinatura", "netflix", "spotify", "prime",
                     "hbo", "max", "disney", "youtube", "deezer", "paramount",
                     "globoplay", "icloud", "chatgpt", "gpt", "openai", "canva",
                     "amazon prime", "crunchyroll", "twitch"]),
    ("alimentacao", ["alimentacao", "comida", "mercado", "supermercado", "almoco",
                     "janta", "jantar", "lanche", "ifood", "rappi", "restaurante",
                     "padaria", "cafe", "pizza", "hamburguer", "burger", "feira",
                     "acougue", "bebida", "cerveja", "mcdonalds", "bk", "subway",
                     "outback", "starbucks", "doce", "sorvete", "marmita", "comer",
                     "delivery", "zedelivery", "açai", "acai", "salgado"]),
    ("transporte", ["transporte", "uber", "indrive", "cabify", "taxi", "gasolina",
                    "combustivel", "posto", "onibus", "metro", "passagem", "brt",
                    "estacionamento", "pedagio", "bilhete", "etanol", "alcool",
                    "blablacar", "corrida", "carro", "moto"]),
    ("moradia", ["moradia", "casa", "luz", "energia", "agua", "aluguel",
                 "condominio", "gas", "internet", "iptu", "faxina", "diarista",
                 "conta de luz", "conta de agua", "wifi", "limpeza"]),
    ("saude", ["saude", "farmacia", "drogaria", "remedio", "medico", "dentista",
               "hospital", "consulta", "exame", "academia", "psicologo", "terapia",
               "unimed", "plano de saude", "vacina", "suplemento"]),
    ("lazer", ["lazer", "cinema", "bar", "balada", "show", "jogo", "passeio",
               "viagem", "role", "festa", "ingresso", "parque", "praia", "hotel",
               "airbnb", "steam", "playstation", "xbox", "boliche", "churrasco"]),
    ("vestuario", ["vestuario", "roupa", "tenis", "camisa", "calca", "sapato",
                   "blusa", "vestido", "loja", "shopping", "bone", "nike", "adidas",
                   "renner", "riachuelo", "zara", "cea", "jaqueta", "moletom"]),
    ("educacao", ["educacao", "curso", "faculdade", "livro", "escola",
                  "mensalidade", "aula", "material", "apostila", "udemy", "alura",
                  "ingles", "facul"]),
]

_CAT_DISPLAY = {
    "alimentacao": "alimentação",
    "transporte": "transporte",
    "moradia": "moradia",
    "saude": "saúde",
    "lazer": "lazer",
    "vestuario": "vestuário",
    "educacao": "educação",
    "assinaturas": "assinaturas",
}

_CAT_PATTERNS = [
    (cat, re.compile(r"\b(?:" + "|".join(re.escape(_strip_accents(k)) for k in kws) + r")\b"))
    for cat, kws in _CAT_KEYWORDS
]


def detectar_categoria(msg_norm: str):
    for cat, pat in _CAT_PATTERNS:
        if pat.search(msg_norm):
            return _CAT_DISPLAY.get(cat, cat)
    return None


# ----------------------------- período -----------------------------

def detectar_periodo(msg_norm: str) -> str:
    if "hoje" in msg_norm:
        return "hoje"
    if "ontem" in msg_norm:
        return "ontem"
    if "semana passada" in msg_norm or "ultima semana" in msg_norm:
        return "semana_passada"
    if "semana" in msg_norm:
        return "semana"
    if "mes passado" in msg_norm:
        return "mes_passado"
    if "ano" in msg_norm:
        return "ano"
    if "tudo" in msg_norm or "geral" in msg_norm or "sempre" in msg_norm:
        return "tudo"
    return "mes"


# ----------------------------- descrição -----------------------------

_STOP = re.compile(
    r"(?i)\b(r\$|reais|real|pila|pilas|conto|contos|mil|k|gastei|paguei|comprei|"
    r"gasto|torrei|recebi|ganhei|caiu|no|na|no|de|do|da|em|um|uma|me|hoje|ontem)\b"
)


def _descricao(msg: str) -> str:
    s = _STOP.sub("", msg)
    s = re.sub(r"\d+(?:[.,]\d+)?", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    return s[:60]


# ----------------------------- frases -----------------------------

_FRASES_GASTO = [
    "Anotado! 🐷 -{v} em {c}. Carteira sentiu, mas tá registrado.",
    "Bele, -{v} em {c} na conta. 💸",
    "Pronto: -{v} em {c}. Cada centavo no controle.",
    "Anotei -{v} em {c}. Doeu? Anotei mesmo assim. 🐷",
    "Registrado: -{v} em {c}. ✅",
    "Tá lá: -{v} em {c}. Bora segurar a onda 💸",
    "Feito, -{v} em {c}. O porquinho chorou um pouco. 🐷",
]
_FRASES_ENTRADA = [
    "Boa! 🤑 +{v} em {c}. Dinheiro na conta!",
    "Eba, +{v} em {c} registrado. Tá rico hein.",
    "Anotado: +{v} em {c}. 💰",
    "+{v} em {c} na conta. Bora multiplicar. 🐷",
    "Chegou grana! +{v} em {c}. 🤑",
]
_FRASES_OI = [
    "E aí! 🐷 Pode mandar do seu jeito:",
    "Opa! 🐷 Tô aqui pra anotar suas finanças. Manda ver:",
    "Salve! 🐷 Bora controlar essa grana:",
]
_AJUDA_EXEMPLOS = (
    "\n• \"gastei 45 no mercado\"\n"
    "• \"recebi 3500 de salário\"\n"
    "• \"quanto gastei essa semana?\"\n"
    "• \"manda o dashboard\" (relatório em PDF)\n"
    "• \"meta do cofrinho 1000\" / \"guardar 50 no cofrinho\" 🐖\n"
    "• \"me avisa se gastar mais de 500 em lazer\"\n"
    "• \"lembretes\" pra ver/ajustar os avisos automáticos\n"
    "• \"quero sair\" pra deslogar"
)

# Resposta quando não entendeu (e/ou a IA está fora) — sem falar de limite.
NUDGE = (
    "Não saquei 100% 🤔. Manda mais ou menos assim:\n"
    "• \"gastei 30 no mercado\"\n"
    "• \"quanto gastei essa semana\"\n"
    "• \"gera um resumo do mês\""
)

# Conversa fiada resolvida localmente (não chama IA).
_SMALLTALK = {
    "kkk": "kkk 🐷", "kkkk": "kkkk 🐷", "haha": "haha 😄", "rsrs": "rsrs 🐷",
    "blz": "Beleza! 👍", "beleza": "Beleza! 👍", "ok": "👍", "okay": "👍",
    "ta": "👍", "tá": "👍", "top": "Top! 🐷", "massa": "Massa! 🐷",
    "entendi": "👍", "tudo bem": "Tudo ótimo por aqui! 🐷 E aí, anotou algum gasto?",
    "tudo bom": "Tudo certo! 🐷 Bora controlar a grana?",
    "de boa": "De boa! 🐷", "valeu mesmo": "Disponível! 🐷",
}


def _confirma(tipo, valor, categoria, desc=""):
    base = random.choice(_FRASES_ENTRADA if tipo == "entrada" else _FRASES_GASTO)
    texto = base.format(v=_fmt(valor), c=categoria)
    if desc and categoria in ("outros", "renda_extra"):
        texto += f" ({desc})"
    return texto


# ----------------------------- intenções -----------------------------

_VERBOS_GASTO = ["gastei", "paguei", "comprei", "gasto", "torrei", "gastando",
                 "pago", "comprando"]
_MARC_ENTRADA = ["recebi", "ganhei", "caiu", "entrou", "me pag", "pagaram",
                 "salario", "freela", "vendi", "vendeu", "rendeu", "pix de"]


_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _cof_progresso(user_id) -> str:
    s = database.get_savings(user_id)
    if s["meta"] and s["meta"] > 0:
        pct = min(100, s["total"] / s["meta"] * 100)
        falta = max(0.0, s["meta"] - s["total"])
        return (f"🐖 Cofrinho: {_fmt(s['total'])} de {_fmt(s['meta'])} "
                f"({pct:.0f}%). Faltam {_fmt(falta)}.")
    if s["total"]:
        return f"🐖 Cofrinho: {_fmt(s['total'])} guardados (sem meta definida)."
    return "🐖 Seu cofrinho tá vazio. Define uma meta: \"meta do cofrinho 1000\"."


def _cofrinho(n, msg, user_id) -> str:
    val = parse_valor(msg)
    if ("meta" in n or "criar" in n or "definir" in n) and val:
        database.set_savings_meta(user_id, val)
        return f"Meta definida! 🐖 {_cof_progresso(user_id)}"
    if val and any(k in n for k in ["tirar", "tira", "saca", "sacar", "resgatar", "retirar"]):
        total = database.add_savings(user_id, -val)
        return f"Tirei {_fmt(val)} do cofrinho. Total agora: {_fmt(total)}."
    if val:  # guardar/depositar (default quando tem valor)
        total = database.add_savings(user_id, val)
        extra = ""
        s = database.get_savings(user_id)
        if s["meta"] and total >= s["meta"]:
            extra = " 🎉 Bateu a meta!"
        return f"Guardado! 🐖 +{_fmt(val)} no cofrinho. Total: {_fmt(total)}.{extra}"
    return _cof_progresso(user_id)


def _lembrete(n, user_id) -> str:
    p = database.get_prefs(user_id)
    ligar = any(k in n for k in ["ligar", "liga", "ativar", "ativa", " on"])
    desligar = any(k in n for k in ["desligar", "desliga", "desativar", "desativa",
                                    " off", "para", "parar", "cancela"])
    m_hora = re.search(r"(\d{1,2})\s*h|as (\d{1,2})|às (\d{1,2})", n)
    hora = None
    if m_hora:
        hora = int(next(g for g in m_hora.groups() if g))

    alvo = None
    if "diario" in n or "dia" in n:
        alvo = "daily"
    elif "semanal" in n or "semana" in n:
        alvo = "weekly"
    elif "cofrinho" in n:
        alvo = "cofrinho"

    if alvo:
        if desligar:
            database.set_pref(user_id, alvo, 0)
        elif ligar:
            database.set_pref(user_id, alvo, 1)
        if hora is not None and 0 <= hora <= 23:
            campo = {"daily": "daily_hour", "weekly": "weekly_hour", "cofrinho": "cof_hour"}[alvo]
            database.set_pref(user_id, campo, hora)
            database.set_pref(user_id, alvo, 1)
        return _status_lembretes(user_id)

    return _status_lembretes(user_id)


def _status_lembretes(user_id) -> str:
    p = database.get_prefs(user_id)
    onoff = lambda x: "ligado" if x else "desligado"
    return (
        "🔔 Seus lembretes:\n"
        f"• Fim do dia: {onoff(p['daily'])} (às {p['daily_hour']}h)\n"
        f"• Semanal: {onoff(p['weekly'])} ({_DIAS[p['weekly_day']]} às {p['weekly_hour']}h)\n"
        f"• Cofrinho: {onoff(p['cofrinho'])} ({_DIAS[p['cof_day']]} às {p['cof_hour']}h)\n\n"
        "Pra mudar: \"lembrete diario 22h\", \"lembrete semanal off\", "
        "\"lembrete cofrinho on\"."
    )


def try_handle(mensagem: str, user_id: int):
    msg = mensagem.strip()
    n = _norm(msg)
    if not n:
        return None

    # 1) Saudações / ajuda
    if n in ("oi", "ola", "ola!", "eai", "e ai", "opa", "bom dia", "boa tarde",
             "boa noite", "ajuda", "help", "menu", "comandos"):
        return {"texto": random.choice(_FRASES_OI) + _AJUDA_EXEMPLOS, "charts": []}

    if n in ("valeu", "vlw", "obrigado", "obrigada", "brigado", "tmj", "show"):
        return {"texto": "Disponível sempre! 🐷", "charts": []}

    if n in _SMALLTALK:
        return {"texto": _SMALLTALK[n], "charts": []}

    # Lembretes 🔔 (checa antes do cofrinho: "lembrete cofrinho off")
    if "lembrete" in n:
        return {"texto": _lembrete(n, user_id), "charts": []}

    # Cofrinho 🐖
    if "cofrinho" in n:
        return {"texto": _cofrinho(n, msg, user_id), "charts": []}

    tem_dash = any(k in n for k in ["dashboard", "relatorio", "painel", "pdf"])
    tem_chart = any(k in n for k in ["grafico", "gera um", "gera o", "comparativo",
                                     "compara", "por dia", "evolucao"])

    # Dashboard em PDF
    if tem_dash:
        ex = ToolExecutor(user_id)
        txt = ex.run("generate_dashboard", {"periodo": detectar_periodo(n)})
        if ex.docs:
            return {"texto": "Teu relatório saiu 📊👇", "charts": [], "docs": ex.docs}
        return {"texto": txt, "charts": [], "docs": []}
    tem_limite = any(k in n for k in ["me avisa", "me avise", "limite", "limita"])
    valor = parse_valor(msg)

    # 2) Limite
    if tem_limite and valor:
        cat = detectar_categoria(n)
        if cat:
            periodo = "semanal" if ("semana" in n or "semanal" in n) else "mensal"
            txt = ToolExecutor(user_id).run(
                "set_limit", {"categoria": cat, "valor": valor, "periodo": periodo}
            )
            return {"texto": f"Combinado! 🐷 {txt} Eu te aviso quando chegar perto.",
                    "charts": []}
        return None  # sem categoria clara -> IA

    # 3) Gráfico
    if tem_chart:
        if "compara" in n or "comparativo" in n or "passado" in n:
            tipo = "comparativo"
        elif "por dia" in n or "linha" in n or "evolu" in n:
            tipo = "linha"
        else:
            tipo = "pizza"
        ex = ToolExecutor(user_id)
        txt = ex.run("generate_chart", {"tipo": tipo, "periodo": detectar_periodo(n)})
        if ex.charts:
            return {"texto": "Saiu fresquinho 📊👇", "charts": ex.charts}
        return {"texto": txt, "charts": []}

    # 4) Registro de transação (tem valor + intenção/categoria)
    is_entrada = any(k in n for k in _MARC_ENTRADA) and "paguei" not in n
    is_gasto = any(k in n for k in _VERBOS_GASTO)
    cat = detectar_categoria(n)

    if valor and (is_entrada or is_gasto or cat):
        ex = ToolExecutor(user_id)
        desc = _descricao(msg)
        if is_entrada:
            if any(k in n for k in ["freela", "vendi", "vendeu", "bico", "extra", "rendeu", "pix"]):
                categoria = "renda_extra"
            else:
                categoria = "renda"
            ex.run("add_transaction", {"tipo": "entrada", "valor": valor,
                                       "categoria": categoria, "descricao": desc})
            return {"texto": _confirma("entrada", valor, categoria, desc), "charts": []}
        else:
            # gasto: categoria detectada OU "outros" (nunca manda pra IA por isso)
            categoria = cat or "outros"
            res = ex.run("add_transaction", {"tipo": "gasto", "valor": valor,
                                             "categoria": categoria, "descricao": desc})
            texto = _confirma("gasto", valor, categoria, desc)
            if "[ALERTA LIMITE]" in res:
                texto += "\n⚠️ Limite: " + res.split("[ALERTA LIMITE]", 1)[1].strip()
            return {"texto": texto, "charts": []}

    # 5) Consulta
    eh_consulta = any(k in n for k in ["quanto", "saldo", "resumo", "extrato",
                                       "balanco", "total", "gastei", "limites",
                                       "meus gastos", "minhas"])
    if eh_consulta and valor is None:
        if "limite" in n or "limites" in n:
            return {"texto": ToolExecutor(user_id).run("get_limits", {}), "charts": []}
        periodo = detectar_periodo(n)
        cat = detectar_categoria(n)
        ex = ToolExecutor(user_id)
        if cat and "gast" in n:
            txt = ex.run("get_transactions",
                         {"periodo": periodo, "categoria": cat, "tipo": "gasto"})
        else:
            txt = ex.run("get_summary", {"periodo": periodo})
        return {"texto": txt, "charts": []}

    # Não sei resolver com confiança -> IA
    return None
