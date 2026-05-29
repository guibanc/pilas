"""Geração de gráficos do PILAS com matplotlib (backend não-interativo)."""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # sem display, salva PNG
import matplotlib.pyplot as plt

import config
import database
import periods

_CHART_BG = "#FFFFFF"


def _ensure_dir():
    os.makedirs(config.CHARTS_DIR, exist_ok=True)


def _outfile(prefix):
    _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(config.CHARTS_DIR, f"{prefix}_{ts}.png")


def _cat_colors():
    return {c["nome"]: (c["cor"] or "#95A5A6") for c in database.list_categories()}


def chart_pizza(user_id, periodo=None):
    """Pizza dos gastos por categoria no período. Retorna (path, resumo)."""
    ini, fim, rotulo = periods.resolve_period(periodo)
    txs = database.query_transactions(user_id, ini, fim, tipo="gasto")
    if not txs:
        return None, f"Sem gastos registrados em {rotulo}."

    por_cat = defaultdict(float)
    for t in txs:
        por_cat[t["categoria"]] += t["valor"]

    cores_map = _cat_colors()
    labels = list(por_cat.keys())
    valores = [por_cat[k] for k in labels]
    cores = [cores_map.get(k, "#95A5A6") for k in labels]
    total = sum(valores)

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.pie(
        valores,
        labels=labels,
        colors=cores,
        autopct=lambda p: f"R$ {p / 100 * total:.0f}",
        startangle=90,
        textprops={"fontsize": 10},
    )
    ax.set_title(f"Gastos por categoria — {rotulo}\nTotal: R$ {total:.2f}", fontsize=13)
    fig.patch.set_facecolor(_CHART_BG)
    path = _outfile("pizza")
    fig.savefig(path, bbox_inches="tight", dpi=110)
    plt.close(fig)
    return path, f"Gráfico de pizza — {rotulo} (total R$ {total:.2f})."


def chart_linha(user_id, periodo=None):
    """Linha de gastos por dia no período. Retorna (path, resumo)."""
    ini, fim, rotulo = periods.resolve_period(periodo or "mes")
    txs = database.query_transactions(user_id, ini, fim, tipo="gasto")
    if not txs:
        return None, f"Sem gastos registrados em {rotulo}."

    por_dia = defaultdict(float)
    for t in txs:
        por_dia[t["data"]] += t["valor"]

    # eixo contínuo de dias
    d0 = datetime.fromisoformat(min(por_dia)).date()
    d1 = datetime.fromisoformat(max(por_dia)).date()
    dias, valores = [], []
    atual = d0
    while atual <= d1:
        iso = atual.isoformat()
        dias.append(atual.strftime("%d/%m"))
        valores.append(por_dia.get(iso, 0.0))
        atual += timedelta(days=1)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(dias, valores, marker="o", color="#3498DB", linewidth=2)
    ax.fill_between(range(len(dias)), valores, alpha=0.15, color="#3498DB")
    ax.set_title(f"Gastos por dia — {rotulo}", fontsize=13)
    ax.set_ylabel("R$")
    ax.grid(True, axis="y", alpha=0.3)
    if len(dias) > 12:
        for i, lbl in enumerate(ax.get_xticklabels()):
            lbl.set_visible(i % 2 == 0)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    fig.patch.set_facecolor(_CHART_BG)
    path = _outfile("linha")
    fig.savefig(path, bbox_inches="tight", dpi=110)
    plt.close(fig)
    total = sum(valores)
    return path, f"Gráfico de linha — {rotulo} (total R$ {total:.2f})."


def chart_comparativo(user_id, periodo=None):
    """Barras comparando gastos por categoria: mês passado vs mês atual."""
    hoje = date.today()
    ini_atual, _ = periods.month_bounds(hoje)
    fim_pass = ini_atual - timedelta(days=1)
    ini_pass, _ = periods.month_bounds(fim_pass)

    tx_atual = database.query_transactions(user_id, ini_atual.isoformat(), hoje.isoformat(), tipo="gasto")
    tx_pass = database.query_transactions(user_id, ini_pass.isoformat(), fim_pass.isoformat(), tipo="gasto")

    if not tx_atual and not tx_pass:
        return None, "Sem gastos nos últimos dois meses pra comparar."

    a, p = defaultdict(float), defaultdict(float)
    for t in tx_atual:
        a[t["categoria"]] += t["valor"]
    for t in tx_pass:
        p[t["categoria"]] += t["valor"]

    cats = sorted(set(a) | set(p))
    val_pass = [p.get(c, 0.0) for c in cats]
    val_atual = [a.get(c, 0.0) for c in cats]

    x = range(len(cats))
    largura = 0.38
    fig, ax = plt.subplots(figsize=(max(7, len(cats) * 1.2), 5))
    ax.bar([i - largura / 2 for i in x], val_pass, largura, label="Mês passado", color="#BDC3C7")
    ax.bar([i + largura / 2 for i in x], val_atual, largura, label="Mês atual", color="#E67E22")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("R$")
    ax.set_title("Comparativo de gastos — mês passado vs atual", fontsize=13)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.patch.set_facecolor(_CHART_BG)
    path = _outfile("comparativo")
    fig.savefig(path, bbox_inches="tight", dpi=110)
    plt.close(fig)
    return path, (
        f"Comparativo — mês passado: R$ {sum(val_pass):.2f} | "
        f"mês atual: R$ {sum(val_atual):.2f}."
    )


def generate(user_id, tipo, periodo=None):
    """Dispatcher. tipo: pizza | linha | comparativo."""
    tipo = (tipo or "pizza").lower()
    if tipo == "linha":
        return chart_linha(user_id, periodo)
    if tipo == "comparativo":
        return chart_comparativo(user_id, periodo)
    return chart_pizza(user_id, periodo)
