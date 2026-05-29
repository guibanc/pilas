"""Cérebro do PILAS: interpreta a mensagem e chama as tools.

Suporta dois provedores (escolhidos via PROVIDER no .env):
  - gemini    -> Google Gemini (tem tier grátis)  [padrão]
  - anthropic -> Claude (pago)

A persona e as tools são compartilhadas; só muda a chamada da API.
"""
import asyncio
import re
from datetime import date

import config
from tools import TOOLS, ToolExecutor

MAX_ITERS = 6
# Espera no máx. esse tempo num 429 antes de desistir e avisar o usuário.
MAX_RETRY_WAIT = 20

# Persona — instrução de sistema compartilhada entre os provedores.
# {{NOME}} é substituído pelo nome do usuário logado.
PERSONA = """Você é o PILAS, um agente financeiro pessoal que vive dentro do Telegram.
Você está conversando com {NOME}. Personalidade: descontraída, direta e levemente \
engraçada — como um amigo que entende de finanças mas não enche o saco com lição de moral.

## Função
Registrar, organizar e analisar gastos e entradas através de conversa natural. \
Nada de formulários ou comandos rígidos: o usuário fala, você entende e age usando as tools.

## Como interpretar
- "gastei 45 no mercado" -> add_transaction(gasto, 45, alimentação)
- "paguei 120 de uber" -> add_transaction(gasto, 120, transporte)
- "conta de luz 180" -> add_transaction(gasto, 180, moradia)
- "recebi meu salário, 3500" -> add_transaction(entrada, 3500, renda)
- "me pagaram 200 de freela" -> add_transaction(entrada, 200, renda_extra)
- "quanto gastei essa semana?" -> get_summary(semana)
- "o que gastei em alimentação esse mês?" -> get_transactions(categoria=alimentação, periodo=mes)
- "me avisa se gastar mais de 500 em lazer por mês" -> set_limit(lazer, 500, mensal)
- "gera um resumo do mês" -> generate_chart(pizza, mes) + comentário com insight
- "ver meus gastos por dia" -> generate_chart(linha, mes)
- "compara esse mês com o passado" -> generate_chart(comparativo)

## Categorias padrão
alimentação, transporte, moradia, saúde, lazer, vestuário, educação, assinaturas, \
renda, renda_extra, outros. Categorize de forma inteligente mesmo sem o usuário dizer. \
Se ficar em dúvida REAL entre duas categorias, pergunte de forma curta.

## Regras
1. Confirme cada registro de forma rápida e bem-humorada (uma linha). \
Ex: "Anotado! 🐷 +R$ 45 em alimentação. Barriga cheia, carteira menos..."
2. Valores sempre em reais (R$). Sem moeda especificada = BRL.
3. Data não mencionada = hoje.
4. Se o usuário citar algo sem valor (ex: "comprei um tênis"), PERGUNTE o valor antes de registrar.
5. Ao registrar um gasto, se vier um aviso de limite no resultado da tool, repasse pro usuário.
6. Em consultas, dê a resposta + no máximo 1 insight curto e relevante. Nunca dê sermão.
7. NUNCA invente dados. Se não houver registro, diga que não tem essa informação.
8. Quando gerar gráfico, a imagem é enviada automaticamente — você só comenta o que ela mostra.

## Tom
Rápido e objetivo. Emojis com moderação (🐷💸📊✅). Use o nome da pessoa às vezes.
Responda sempre em português do Brasil."""


def _persona(nome):
    return PERSONA.format(NOME=nome or "você")


def _system_text(nome):
    return _persona(nome) + f"\n\nContexto atual: hoje é {date.today().isoformat()}."


async def responder(historico: list[dict], mensagem: str, user_id: int, nome: str = ""):
    """Processa uma mensagem de um usuário logado.

    `historico`: trocas anteriores no formato {role, content(str)}.
    Retorna (texto_resposta, [caminhos_de_graficos], _).
    """
    if config.PROVIDER == "anthropic":
        return await _responder_anthropic(historico, mensagem, user_id, nome)
    return await _responder_gemini(historico, mensagem, user_id, nome)


# =========================== GEMINI (grátis) ===========================

_gemini_clients = None
_key_cursor = 0  # round-robin entre as chaves


def _get_gemini_clients():
    global _gemini_clients
    if _gemini_clients is None:
        from google import genai

        _gemini_clients = [genai.Client(api_key=k) for k in config.GEMINI_KEYS]
    return _gemini_clients


def _gemini_tools():
    """Converte os schemas das tools para function declarations do Gemini."""
    from google.genai import types

    decls = []
    for t in TOOLS:
        schema = t["input_schema"]
        # Gemini não aceita 'parameters' com objeto vazio; usa None nesses casos.
        params = schema if schema.get("properties") else None
        decls.append(
            types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters=params
            )
        )
    return [types.Tool(function_declarations=decls)]


def _gemini_history(historico):
    """Converte {role, content} para Content do Gemini (assistant -> model)."""
    from google.genai import types

    contents = []
    for m in historico:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    return contents


class _QuotaError(Exception):
    """Limite do tier grátis estourou e a espera é longa demais."""

    def __init__(self, segundos):
        self.segundos = segundos


def _parse_retry_seconds(msg: str) -> float:
    """Extrai o tempo de espera sugerido de um erro 429 do Gemini."""
    for padrao in (r"retry in ([\d.]+)s", r"retryDelay'?:?\s*'?(\d+)s"):
        m = re.search(padrao, msg)
        if m:
            return float(m.group(1))
    return 10.0


def _is_429(msg: str) -> bool:
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


async def _pass_chaves(clients, contents, cfg):
    """Tenta cada chave uma vez (round-robin). Retorna (resp, menor_espera).

    resp != None -> deu certo em alguma chave.
    resp == None -> todas estavam em 429; menor_espera = menor retry sugerido.
    """
    global _key_cursor
    n = len(clients)
    menor = None
    for off in range(n):
        idx = (_key_cursor + off) % n
        try:
            resp = await clients[idx].aio.models.generate_content(
                model=config.GEMINI_MODEL, contents=contents, config=cfg
            )
            _key_cursor = (idx + 1) % n  # próxima chamada começa na seguinte
            return resp, None
        except Exception as e:
            msg = str(e)
            if not _is_429(msg):
                raise
            d = _parse_retry_seconds(msg)
            menor = d if menor is None else min(menor, d)
    return None, menor


async def _gemini_generate(clients, contents, cfg):
    """Gera conteúdo rotacionando entre as chaves; espera só se TODAS estourarem."""
    for _ in range(3):
        resp, menor = await _pass_chaves(clients, contents, cfg)
        if resp is not None:
            return resp
        if menor is None or menor > MAX_RETRY_WAIT:
            raise _QuotaError(round(menor or 10))
        await asyncio.sleep(menor + 1)  # todas no limite, mas espera curta
    raise _QuotaError(10)


async def _responder_gemini(historico, mensagem, user_id, nome):
    from google.genai import types

    clients = _get_gemini_clients()
    executor = ToolExecutor(user_id)

    cfg = types.GenerateContentConfig(
        system_instruction=_system_text(nome),
        tools=_gemini_tools(),
        # desliga a execução automática: queremos rodar as tools nós mesmos
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.4,
    )

    contents = _gemini_history(historico)
    contents.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))

    texto_final = ""
    for _ in range(MAX_ITERS):
        try:
            resp = await _gemini_generate(clients, contents, cfg)
        except _QuotaError:
            if texto_final:  # já tinha algo útil; devolve isso
                return texto_final, executor.charts, contents
            raise  # sem nada: deixa o bot responder com a dica amigável

        cand = resp.candidates[0] if resp.candidates else None
        parts = (cand.content.parts if cand and cand.content else None) or []

        texto = "".join(p.text for p in parts if getattr(p, "text", None)).strip()
        if texto:
            texto_final = texto

        fcalls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        if not fcalls:
            break

        # registra a vez do modelo (com as chamadas) e devolve os resultados
        contents.append(cand.content)
        fr_parts = []
        for fc in fcalls:
            saida = executor.run(fc.name, dict(fc.args or {}))
            fr_parts.append(
                types.Part.from_function_response(
                    name=fc.name, response={"result": saida}
                )
            )
        contents.append(types.Content(role="user", parts=fr_parts))
    else:
        texto_final = texto_final or "Travei aqui processando isso. Tenta de novo? 🐷"

    return texto_final, executor.charts, contents


# =========================== ANTHROPIC (pago) ==========================

_anthropic_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def _anthropic_system(nome):
    return [
        {"type": "text", "text": _persona(nome), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Contexto atual: hoje é {date.today().isoformat()}."},
    ]


async def _responder_anthropic(historico, mensagem, user_id, nome):
    client = _get_anthropic()
    executor = ToolExecutor(user_id)
    messages = list(historico) + [{"role": "user", "content": mensagem}]

    texto_final = ""
    for _ in range(MAX_ITERS):
        resp = await client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            output_config={"effort": config.EFFORT},
            system=_anthropic_system(nome),
            tools=TOOLS,
            messages=messages,
        )

        texto_final = (
            "".join(b.text for b in resp.content if b.type == "text").strip()
            or texto_final
        )

        if resp.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            break

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                saida = executor.run(block.name, block.input or {})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": saida,
                    }
                )
        messages.append({"role": "user", "content": tool_results})
    else:
        texto_final = texto_final or "Travei aqui processando isso. Tenta de novo? 🐷"

    return texto_final, executor.charts, messages
