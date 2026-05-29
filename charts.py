"""Geração de gráficos e dashboard (PDF) do PILAS — visual caprichado."""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # sem display, salva arquivo
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

import config
import database
import periods

# ----------------------------- estilo -----------------------------

_BG = "#FAFAF7"
_INK = "#2B2B2B"
_MUT = "#7A7A7A"
_GREEN = "#27AE60"
_RED = "#E74C3C"
_ACCENT = "#E67E22"


def _style():
    plt.rcParams.update({
        "figure.facecolor": _BG,
        "savefig.facecolor": _BG,
        "axes.facecolor": _BG,
        "axes.edgecolor": "#E2E0D8",
        "axes.grid": True,
        "grid.color": "#ECEAE2",
        "grid.linewidth": 1,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 11,
        "font.family": "DejaVu Sans",
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "text.color": _INK,
        "axes.labelcolor": _MUT,
        "xtick.color": _MUT,
        "ytick.color": _MUT,
    })


def _money(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ensure_dir():
    os.makedirs(config.CHARTS_DIR, exist_ok=True)


def _outfile(prefix, ext="png"):
    _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(config.CHARTS_DIR, f"{prefix}_{ts}.{ext}")


def _cat_colors():
    return {c["nome"]: (c["cor"] or "#95A5A6") for c in database.list_categories()}


def _gastos_por_cat(txs):
    d = defaultdict(float)
    for t in txs:
        if t["tipo"] == "gasto":
            d[t["categoria"]] += t["valor"]
    return dict(sorted(d.items(), key=lambda x: x[1], reverse=True))


# ----------------------------- pizza (donut) -----------------------------

def chart_pizza(user_id, periodo=None):
    _style()
    ini, fim, rotulo = periods.resolve_period(periodo)
    txs = database.query_transactions(user_id, ini, fim, tipo="gasto")
    if not txs:
        return None, f"Sem gastos registrados em {rotulo}."

    por_cat = _gastos_por_cat(txs)
    cores_map = _cat_colors()
    labels = list(por_cat)
    valores = list(por_cat.values())
    cores = [cores_map.get(k, "#95A5A6") for k in labels]
    total = sum(valores)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, _ = ax.pie(
        valores, colors=cores, startangle=90,
        wedgeprops=dict(width=0.42, edgecolor=_BG, linewidth=2),
    )
    # total no centro
    ax.text(0, 0.08, "Total", ha="center", va="center", fontsize=12, color=_MUT)
    ax.text(0, -0.12, _money(total), ha="center", va="center",
            fontsize=16, fontweight="bold", color=_INK)
    # legenda com valor e %
    leg = [f"{l}  —  {_money(v)}  ({v / total * 100:.0f}%)"
           for l, v in zip(labels, valores)]
    ax.legend(wedges, leg, loc="center left", bbox_to_anchor=(1.0, 0.5),
              frameon=False, fontsize=10)
    ax.set_title(f"Gastos por categoria · {rotulo}", pad=18, loc="left")
    fig.subplots_adjust(left=0.02, right=0.62, top=0.88, bottom=0.06)
    path = _outfile("pizza")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path, f"Pizza de gastos · {rotulo} (total {_money(total)})."


# ----------------------------- linha por dia -----------------------------

def chart_linha(user_id, periodo=None):
    _style()
    ini, fim, rotulo = periods.resolve_period(periodo or "mes")
    txs = database.query_transactions(user_id, ini, fim, tipo="gasto")
    if not txs:
        return None, f"Sem gastos registrados em {rotulo}."

    por_dia = defaultdict(float)
    for t in txs:
        por_dia[t["data"]] += t["valor"]
    d0 = datetime.fromisoformat(min(por_dia)).date()
    d1 = datetime.fromisoformat(max(por_dia)).date()
    dias, valores, atual = [], [], d0
    while atual <= d1:
        dias.append(atual.strftime("%d/%m"))
        valores.append(por_dia.get(atual.isoformat(), 0.0))
        atual += timedelta(days=1)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dias, valores, marker="o", markersize=5, color=_ACCENT, linewidth=2.2)
    ax.fill_between(range(len(dias)), valores, alpha=0.12, color=_ACCENT)
    ax.set_title(f"Gastos por dia · {rotulo}", loc="left", pad=14)
    ax.set_ylabel("R$")
    ax.margins(x=0.02)
    if len(dias) > 12:
        step = max(1, len(dias) // 12)
        for i, lbl in enumerate(ax.get_xticklabels()):
            lbl.set_visible(i % step == 0)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    fig.tight_layout()
    path = _outfile("linha")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path, f"Linha de gastos · {rotulo} (total {_money(sum(valores))})."


# ----------------------------- comparativo -----------------------------

def chart_comparativo(user_id, periodo=None):
    _style()
    hoje = date.today()
    ini_atual, _ = periods.month_bounds(hoje)
    fim_pass = ini_atual - timedelta(days=1)
    ini_pass, _ = periods.month_bounds(fim_pass)

    tx_atual = database.query_transactions(user_id, ini_atual.isoformat(), hoje.isoformat(), tipo="gasto")
    tx_pass = database.query_transactions(user_id, ini_pass.isoformat(), fim_pass.isoformat(), tipo="gasto")
    if not tx_atual and not tx_pass:
        return None, "Sem gastos nos últimos dois meses pra comparar."

    a, p = _gastos_por_cat(tx_atual), _gastos_por_cat(tx_pass)
    cats = sorted(set(a) | set(p), key=lambda c: a.get(c, 0) + p.get(c, 0), reverse=True)
    vp = [p.get(c, 0.0) for c in cats]
    va = [a.get(c, 0.0) for c in cats]

    y = range(len(cats))
    h = 0.38
    fig, ax = plt.subplots(figsize=(9, max(4, len(cats) * 0.7)))
    ax.barh([i + h / 2 for i in y], vp, h, label="Mês passado", color="#C9C4B8")
    ax.barh([i - h / 2 for i in y], va, h, label="Mês atual", color=_ACCENT)
    ax.set_yticks(list(y))
    ax.set_yticklabels(cats)
    ax.invert_yaxis()
    ax.set_xlabel("R$")
    ax.set_title("Comparativo · mês passado vs atual", loc="left", pad=14)
    ax.legend(frameon=False)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    path = _outfile("comparativo")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path, (f"Comparativo · passado {_money(sum(vp))} | atual {_money(sum(va))}.")


# ----------------------------- dashboard PDF -----------------------------

def dashboard_pdf(user_id, periodo=None, nome=""):
    """Relatório completo em PDF: KPIs + donut + top categorias + linha por dia."""
    _style()
    ini, fim, rotulo = periods.resolve_period(periodo)
    txs = database.query_transactions(user_id, ini, fim)
    entradas = sum(t["valor"] for t in txs if t["tipo"] == "entrada")
    gastos = sum(t["valor"] for t in txs if t["tipo"] == "gasto")
    saldo = entradas - gastos
    por_cat = _gastos_por_cat(txs)
    cores_map = _cat_colors()

    fig = plt.figure(figsize=(8.27, 11.69))  # A4 retrato
    gs = GridSpec(3, 2, figure=fig, height_ratios=[0.8, 1.3, 1.1],
                  hspace=0.45, wspace=0.25,
                  left=0.08, right=0.94, top=0.92, bottom=0.06)

    titulo = f"Relatório PILAS · {rotulo}"
    if nome:
        titulo = f"{nome} · " + titulo
    fig.suptitle(titulo, x=0.08, y=0.965, ha="left", fontsize=16, fontweight="bold")

    # --- KPIs (linha de cima) ---
    kpis = [("Entradas", entradas, _GREEN), ("Gastos", gastos, _RED),
            ("Saldo", saldo, _GREEN if saldo >= 0 else _RED)]
    ax_k = fig.add_subplot(gs[0, :])
    ax_k.axis("off")
    for i, (lbl, val, cor) in enumerate(kpis):
        x = 0.04 + i * 0.33
        ax_k.add_patch(plt.Rectangle((x, 0.15), 0.29, 0.7, transform=ax_k.transAxes,
                                     facecolor="white", edgecolor="#E2E0D8", lw=1.2,
                                     zorder=1, clip_on=False))
        ax_k.text(x + 0.145, 0.62, lbl, transform=ax_k.transAxes, ha="center",
                  fontsize=11, color=_MUT)
        ax_k.text(x + 0.145, 0.34, _money(val), transform=ax_k.transAxes, ha="center",
                  fontsize=15, fontweight="bold", color=cor)

    # --- Donut (esquerda) ---
    ax_d = fig.add_subplot(gs[1, 0])
    if por_cat:
        labels = list(por_cat); valores = list(por_cat.values())
        cores = [cores_map.get(k, "#95A5A6") for k in labels]
        ax_d.pie(valores, colors=cores, startangle=90,
                 wedgeprops=dict(width=0.42, edgecolor=_BG, linewidth=2))
        ax_d.text(0, 0, _money(gastos), ha="center", va="center",
                  fontsize=12, fontweight="bold")
        ax_d.set_title("Por categoria", loc="center", fontsize=12)
    else:
        ax_d.axis("off")
        ax_d.text(0.5, 0.5, "sem gastos", ha="center", color=_MUT)

    # --- Top categorias (direita, barh) ---
    ax_t = fig.add_subplot(gs[1, 1])
    if por_cat:
        top = list(por_cat.items())[:6][::-1]
        nomes = [t[0] for t in top]; vals = [t[1] for t in top]
        cores = [cores_map.get(k, "#95A5A6") for k in nomes]
        ax_t.barh(nomes, vals, color=cores)
        for i, v in enumerate(vals):
            ax_t.text(v, i, "  " + _money(v), va="center", fontsize=9, color=_INK)
        ax_t.set_title("Top categorias", loc="left", fontsize=12)
        ax_t.grid(axis="y", visible=False)
        ax_t.margins(x=0.18)
    else:
        ax_t.axis("off")

    # --- Linha por dia (baixo, largura total) ---
    ax_l = fig.add_subplot(gs[2, :])
    gastos_tx = [t for t in txs if t["tipo"] == "gasto"]
    if gastos_tx:
        por_dia = defaultdict(float)
        for t in gastos_tx:
            por_dia[t["data"]] += t["valor"]
        d0 = datetime.fromisoformat(min(por_dia)).date()
        d1 = datetime.fromisoformat(max(por_dia)).date()
        dias, vals, atual = [], [], d0
        while atual <= d1:
            dias.append(atual.strftime("%d/%m"))
            vals.append(por_dia.get(atual.isoformat(), 0.0))
            atual += timedelta(days=1)
        ax_l.plot(dias, vals, marker="o", markersize=4, color=_ACCENT, linewidth=2)
        ax_l.fill_between(range(len(dias)), vals, alpha=0.12, color=_ACCENT)
        ax_l.set_title("Evolução diária", loc="left", fontsize=12)
        ax_l.set_ylabel("R$")
        if len(dias) > 12:
            step = max(1, len(dias) // 12)
            for i, lbl in enumerate(ax_l.get_xticklabels()):
                lbl.set_visible(i % step == 0)
        plt.setp(ax_l.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    else:
        ax_l.axis("off")
        ax_l.text(0.5, 0.5, "sem gastos no período", ha="center", color=_MUT)

    path = _outfile("dashboard", "pdf")
    fig.savefig(path)
    plt.close(fig)
    return path, f"Dashboard · {rotulo} (saldo {_money(saldo)})."


# ----------------------------- dispatcher -----------------------------

def generate(user_id, tipo, periodo=None):
    tipo = (tipo or "pizza").lower()
    if tipo == "linha":
        return chart_linha(user_id, periodo)
    if tipo == "comparativo":
        return chart_comparativo(user_id, periodo)
    return chart_pizza(user_id, periodo)
