"""Definição e execução das tools do PILAS.

`TOOLS` é a lista de schemas passada pra API da Claude.
`ToolExecutor` executa cada tool contra o banco e acumula os gráficos
gerados na conversa (pra o bot enviar as imagens depois do loop).
"""
from collections import defaultdict
from datetime import date

import charts
import database
import periods

# ----------------------------- schemas -----------------------------

TOOLS = [
    {
        "name": "add_transaction",
        "description": (
            "Registra uma transação financeira (gasto ou entrada). "
            "Use sempre que o usuário mencionar que gastou, pagou, comprou, "
            "recebeu ou ganhou dinheiro. A data é opcional (default: hoje)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["gasto", "entrada"]},
                "valor": {"type": "number", "description": "Valor em reais (positivo)"},
                "categoria": {
                    "type": "string",
                    "description": "Categoria da transação (ex: alimentação, transporte)",
                },
                "descricao": {"type": "string", "description": "Descrição curta opcional"},
                "data": {
                    "type": "string",
                    "description": "Data ISO 'YYYY-MM-DD'. Omita para usar hoje.",
                },
            },
            "required": ["tipo", "valor", "categoria"],
        },
    },
    {
        "name": "get_transactions",
        "description": (
            "Consulta transações com filtros opcionais. Use para listar ou "
            "somar gastos/entradas de um período ou categoria específica."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {
                    "type": "string",
                    "description": "hoje, ontem, semana, semana_passada, mes, mes_passado, ano, tudo",
                },
                "categoria": {"type": "string"},
                "tipo": {"type": "string", "enum": ["gasto", "entrada"]},
            },
        },
    },
    {
        "name": "get_summary",
        "description": (
            "Resumo financeiro de um período: total de gastos, entradas, saldo "
            "e quebra por categoria. Use para perguntas tipo 'quanto gastei essa semana?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {
                    "type": "string",
                    "description": "hoje, semana, mes, mes_passado, ano, tudo (default mes)",
                }
            },
        },
    },
    {
        "name": "set_limit",
        "description": "Define um limite de gasto para uma categoria, mensal ou semanal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {"type": "string"},
                "valor": {"type": "number"},
                "periodo": {"type": "string", "enum": ["mensal", "semanal"]},
            },
            "required": ["categoria", "valor", "periodo"],
        },
    },
    {
        "name": "get_limits",
        "description": "Lista todos os limites de gasto definidos.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "generate_chart",
        "description": (
            "Gera um gráfico como imagem. tipo: 'pizza' (gastos por categoria), "
            "'linha' (gastos por dia) ou 'comparativo' (mês atual vs passado). "
            "A imagem é enviada automaticamente ao usuário."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["pizza", "linha", "comparativo"]},
                "periodo": {"type": "string", "description": "semana, mes, mes_passado, ano..."},
            },
            "required": ["tipo"],
        },
    },
    {
        "name": "generate_dashboard",
        "description": (
            "Gera um relatório completo em PDF (dashboard) com saldo, gastos por "
            "categoria, top categorias e evolução diária. Use quando pedirem "
            "'dashboard', 'relatório', 'PDF' ou um resumo bonitão do período."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "description": "semana, mes, mes_passado, ano..."}
            },
        },
    },
    {
        "name": "get_categories",
        "description": "Lista as categorias existentes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_category",
        "description": "Cria uma nova categoria de transação.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string"}},
            "required": ["nome"],
        },
    },
]


def _fmt(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class ToolExecutor:
    """Executa tools de UM usuário e guarda os gráficos gerados nesta rodada."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.charts: list[str] = []  # PNGs a enviar (send_photo)
        self.docs: list[str] = []    # PDFs a enviar (send_document)

    # -------- dispatcher --------
    def run(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return f"Tool desconhecida: {name}"
        try:
            return handler(args)
        except Exception as e:  # devolve erro pro modelo se recuperar
            return f"Erro ao executar {name}: {e}"

    # -------- tools --------
    def _add_transaction(self, a):
        tipo = a["tipo"]
        valor = float(a["valor"])
        categoria = a.get("categoria", "outros").strip().lower()
        descricao = a.get("descricao", "")
        data = a.get("data") or date.today().isoformat()

        if not database.category_exists(categoria):
            database.insert_category(categoria)

        tx_id = database.insert_transaction(self.user_id, tipo, valor, categoria, descricao, data)
        resultado = (
            f"OK: {tipo} de {_fmt(valor)} em '{categoria}' "
            f"registrado (id {tx_id}, data {data})."
        )

        # checagem proativa de limite (só pra gastos)
        if tipo == "gasto":
            aviso = self._checar_limite(categoria)
            if aviso:
                resultado += " " + aviso
        return resultado

    def _checar_limite(self, categoria) -> str:
        lim = database.get_limit_for_category(self.user_id, categoria)
        if not lim:
            return ""
        periodo_chave = "semana" if lim["periodo"] == "semanal" else "mes"
        ini, fim, _ = periods.resolve_period(periodo_chave)
        txs = database.query_transactions(self.user_id, ini, fim, categoria=categoria, tipo="gasto")
        gasto = sum(t["valor"] for t in txs)
        teto = lim["valor_limite"]
        pct = (gasto / teto * 100) if teto else 0
        if gasto > teto:
            return (
                f"[ALERTA LIMITE] '{categoria}' ESTOUROU: {_fmt(gasto)} de "
                f"{_fmt(teto)} ({pct:.0f}%) no período {lim['periodo']}."
            )
        if pct >= 80:
            return (
                f"[ALERTA LIMITE] '{categoria}' em {pct:.0f}% do limite "
                f"({_fmt(gasto)} de {_fmt(teto)}, {lim['periodo']})."
            )
        return ""

    def _get_transactions(self, a):
        ini, fim, rotulo = periods.resolve_period(a.get("periodo"))
        categoria = (a.get("categoria") or "").strip().lower() or None
        tipo = a.get("tipo")
        txs = database.query_transactions(self.user_id, ini, fim, categoria=categoria, tipo=tipo)
        if not txs:
            return f"Nenhuma transação encontrada ({rotulo})."
        linhas = [
            f"- {t['data']} | {t['tipo']} | {_fmt(t['valor'])} | {t['categoria']}"
            + (f" | {t['descricao']}" if t["descricao"] else "")
            for t in txs[:30]
        ]
        total = sum(t["valor"] for t in txs)
        cab = f"{len(txs)} transação(ões) em {rotulo}. Total: {_fmt(total)}."
        return cab + "\n" + "\n".join(linhas)

    def _get_summary(self, a):
        ini, fim, rotulo = periods.resolve_period(a.get("periodo"))
        txs = database.query_transactions(self.user_id, ini, fim)
        gastos = sum(t["valor"] for t in txs if t["tipo"] == "gasto")
        entradas = sum(t["valor"] for t in txs if t["tipo"] == "entrada")
        por_cat = defaultdict(float)
        for t in txs:
            if t["tipo"] == "gasto":
                por_cat[t["categoria"]] += t["valor"]
        ranking = sorted(por_cat.items(), key=lambda x: x[1], reverse=True)
        cat_txt = "\n".join(f"  - {c}: {_fmt(v)}" for c, v in ranking) or "  (sem gastos)"
        return (
            f"Resumo de {rotulo}:\n"
            f"Entradas: {_fmt(entradas)}\n"
            f"Gastos: {_fmt(gastos)}\n"
            f"Saldo: {_fmt(entradas - gastos)}\n"
            f"Gastos por categoria:\n{cat_txt}"
        )

    def _set_limit(self, a):
        categoria = a["categoria"].strip().lower()
        valor = float(a["valor"])
        periodo = a["periodo"]
        if not database.category_exists(categoria):
            database.insert_category(categoria)
        database.upsert_limit(self.user_id, categoria, valor, periodo)
        return f"Limite definido: {_fmt(valor)} {periodo} em '{categoria}'."

    def _get_limits(self, a):
        lims = database.list_limits(self.user_id)
        if not lims:
            return "Nenhum limite definido."
        return "Limites:\n" + "\n".join(
            f"- {l['categoria']}: {_fmt(l['valor_limite'])} ({l['periodo']})" for l in lims
        )

    def _generate_chart(self, a):
        path, resumo = charts.generate(self.user_id, a["tipo"], a.get("periodo"))
        if path:
            self.charts.append(path)
            return f"OK, gráfico gerado e será enviado. {resumo}"
        return resumo  # ex: "Sem gastos no período"

    def _generate_dashboard(self, a):
        path, resumo = charts.dashboard_pdf(
            self.user_id, a.get("periodo"), a.get("nome", "")
        )
        if path:
            self.docs.append(path)
            return f"OK, dashboard em PDF gerado e será enviado. {resumo}"
        return resumo

    def _get_categories(self, a):
        cats = database.list_categories()
        return "Categorias: " + ", ".join(c["nome"] for c in cats)

    def _add_category(self, a):
        nome = a["nome"].strip().lower()
        criada = database.insert_category(nome)
        return f"Categoria '{nome}' criada." if criada else f"Categoria '{nome}' já existia."
