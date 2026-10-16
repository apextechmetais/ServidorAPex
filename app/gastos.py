"""Gastos e métricas: quanto foi gasto (ou recebido) por dia, semana, mês, períodos maiores e ano.

A base são os pagamentos registrados (baixas). Contas antigas, marcadas como pagas antes das baixas
detalhadas, entram pela data de pagamento (ou vencimento) com o valor pago.
"""
from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required

from .models import Nota
from .util import hoje_sp, somar_meses

gastos_bp = Blueprint("gastos", __name__)

ZERO = Decimal("0")
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def movimentos(tipo):
    """Lista de (data, valor, nota) de dinheiro que saiu (tipo='saida') ou entrou ('entrada')."""
    lista = []
    for n in Nota.query.filter(Nota.tipo == tipo, Nota.status != "Cancelado").all():
        if n.pagamentos:
            lista.extend((p.data, p.valor, n) for p in n.pagamentos)
        elif n.status in ("Pago", "Recebido", "Parcial") and (n.valor_pago or ZERO) > 0:
            lista.append((n.data_pagamento or n.data_vencimento or n.data_emissao, n.valor_pago, n))
        elif n.status in ("Pago", "Recebido"):
            lista.append((n.data_pagamento or n.data_vencimento or n.data_emissao, n.valor, n))
    return [m for m in lista if m[0]]


def soma(movs, ini, fim):
    return sum((v for d, v, _ in movs if ini <= d <= fim), ZERO)


def inicio_semana(d):
    return d - timedelta(days=d.weekday())  # segunda-feira


def periodo_escolhido(args, hoje):
    """Devolve (inicio, fim, rótulo, chave) a partir dos filtros da tela."""
    from .notas import parse_data
    p = args.get("periodo", "mes")
    if p == "hoje":
        return hoje, hoje, "Hoje", p
    if p == "semana":
        return inicio_semana(hoje), hoje, "Esta semana", p
    if p == "7dias":
        return hoje - timedelta(days=6), hoje, "Últimos 7 dias", p
    if p == "30dias":
        return hoje - timedelta(days=29), hoje, "Últimos 30 dias", p
    if p == "3meses":
        return somar_meses(hoje.replace(day=1), -2), hoje, "Últimos 3 meses", p
    if p == "6meses":
        return somar_meses(hoje.replace(day=1), -5), hoje, "Últimos 6 meses", p
    if p == "12meses":
        return somar_meses(hoje.replace(day=1), -11), hoje, "Últimos 12 meses", p
    if p == "ano":
        ano = args.get("ano", type=int) or hoje.year
        fim = date(ano, 12, 31)
        return date(ano, 1, 1), min(fim, hoje) if ano == hoje.year else fim, f"Ano de {ano}", p
    if p == "personalizado":
        ini = parse_data(args.get("de", "")) or hoje.replace(day=1)
        fim = parse_data(args.get("ate", "")) or hoje
        if fim < ini:
            ini, fim = fim, ini
        return ini, fim, f"{ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}", p
    return hoje.replace(day=1), hoje, f"{MESES[hoje.month - 1]}/{hoje.year} (mês atual)", "mes"


def serie(movs, ini, fim):
    """Agrupa por dia (até 31 dias), semana (até ~4 meses) ou mês."""
    dias = (fim - ini).days + 1
    grupos = OrderedDict()
    if dias <= 31:
        escala = "dia"
        d = ini
        while d <= fim:
            grupos[d.strftime("%d/%m")] = (d, d)
            d += timedelta(days=1)
    elif dias <= 124:
        escala = "semana"
        d = inicio_semana(ini)
        while d <= fim:
            grupos["Sem. " + max(d, ini).strftime("%d/%m")] = (max(d, ini), min(d + timedelta(days=6), fim))
            d += timedelta(days=7)
    else:
        escala = "mês"
        d = ini.replace(day=1)
        while d <= fim:
            prox = somar_meses(d, 1)
            grupos[f"{MESES[d.month - 1]}/{str(d.year)[2:]}"] = (max(d, ini), min(prox - timedelta(days=1), fim))
            d = prox
    rotulos = list(grupos.keys())
    valores = [float(soma(movs, a, b)) for a, b in grupos.values()]
    return escala, rotulos, valores


@gastos_bp.route("/gastos")
@login_required
def painel():
    hoje = hoje_sp()
    tipo = "entrada" if request.args.get("fluxo") == "entrada" else "saida"
    movs = movimentos(tipo)

    fixos = {
        "hoje": soma(movs, hoje, hoje),
        "ontem": soma(movs, hoje - timedelta(days=1), hoje - timedelta(days=1)),
        "semana": soma(movs, inicio_semana(hoje), hoje),
        "semana_passada": soma(movs, inicio_semana(hoje) - timedelta(days=7), inicio_semana(hoje) - timedelta(days=1)),
        "mes": soma(movs, hoje.replace(day=1), hoje),
        "mes_passado": soma(movs, somar_meses(hoje.replace(day=1), -1), hoje.replace(day=1) - timedelta(days=1)),
        "ano": soma(movs, date(hoje.year, 1, 1), hoje),
        "ano_passado": soma(movs, date(hoje.year - 1, 1, 1), date(hoje.year - 1, 12, 31)),
    }

    ini, fim, rotulo, chave = periodo_escolhido(request.args, hoje)
    dias = (fim - ini).days + 1
    no_periodo = [(d, v, n) for d, v, n in movs if ini <= d <= fim]
    total = sum((v for _, v, _ in no_periodo), ZERO)
    anterior_ini, anterior_fim = ini - timedelta(days=dias), ini - timedelta(days=1)
    total_anterior = soma(movs, anterior_ini, anterior_fim)
    variacao = (float(total / total_anterior - 1) * 100) if total_anterior > 0 else None

    por_categoria = defaultdict(lambda: ZERO)
    por_fornecedor = defaultdict(lambda: ZERO)
    for _, v, n in no_periodo:
        por_categoria[n.categoria or "Sem categoria"] += v
        por_fornecedor[n.cliente_fornecedor or "Sem fornecedor"] += v
    categorias = sorted(por_categoria.items(), key=lambda x: -x[1])
    fornecedores = sorted(por_fornecedor.items(), key=lambda x: -x[1])[:10]
    maiores = sorted(no_periodo, key=lambda m: -m[1])[:10]

    escala, rotulos, valores = serie(movs, ini, fim)

    anos = sorted({d.year for d, _, _ in movs} | {hoje.year}, reverse=True)
    return render_template(
        "gastos.html", hoje=hoje, tipo=tipo, fixos=fixos, filtros=request.args, chave=chave, rotulo=rotulo,
        ini=ini, fim=fim, dias=dias, total=total, qtd=len(no_periodo), total_anterior=total_anterior,
        anterior_ini=anterior_ini, anterior_fim=anterior_fim, variacao=variacao,
        media_dia=total / dias, media_semana=total / Decimal(dias) * 7, media_mes=total / Decimal(dias) * Decimal("30.44"),
        categorias=categorias, fornecedores=fornecedores, maiores=maiores,
        escala=escala, serie_rotulos=rotulos, serie_valores=valores, anos=anos,
    )
