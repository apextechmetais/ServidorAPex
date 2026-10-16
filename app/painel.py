"""Visão geral financeira, detalhe de cada cobrança e registro de pagamentos (baixas)."""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import db
from .models import Nota, Pagamento, DocumentoEmpresa, LogAuditoria
from .util import hoje_sp, somar_meses
from .arquivos import salvar_upload, excluir_arquivo

painel_bp = Blueprint("painel", __name__)

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
ZERO = Decimal("0")


def _pagamentos_no_periodo(nota, inicio, fim):
    """Quanto desta conta foi pago/recebido entre inicio e fim (inclusive)."""
    if nota.pagamentos:
        return sum((p.valor for p in nota.pagamentos if inicio <= p.data <= fim), ZERO)
    # Contas antigas, sem baixas registradas: usa o status e a data de pagamento
    if nota.status in ("Pago", "Recebido"):
        data = nota.data_pagamento or nota.data_vencimento or nota.data_emissao
        if data and inicio <= data <= fim:
            return nota.valor_pago if (nota.valor_pago or ZERO) > 0 else nota.valor
    elif nota.status == "Parcial" and nota.data_pagamento and inicio <= nota.data_pagamento <= fim:
        return nota.valor_pago or ZERO
    return ZERO


def recalcular_situacao(nota):
    """Valor pago, status e data de pagamento a partir das baixas registradas."""
    total = sum((p.valor for p in nota.pagamentos), ZERO)
    nota.valor_pago = total
    if nota.quitada and nota.pagamentos:
        # Quitada na baixa (desconto, acordo): fica paga mesmo com valor menor
        nota.status = "Recebido" if nota.tipo == "entrada" else "Pago"
        nota.data_pagamento = max(p.data for p in nota.pagamentos)
    elif total <= 0:
        if nota.status in ("Pago", "Recebido", "Parcial"):
            nota.status = "Pendente"
        nota.data_pagamento = None
    elif total >= (nota.valor or ZERO):
        nota.status = "Recebido" if nota.tipo == "entrada" else "Pago"
        nota.data_pagamento = max(p.data for p in nota.pagamentos)
    else:
        nota.status = "Parcial"
        nota.data_pagamento = max(p.data for p in nota.pagamentos)


def quitar_conta(nota, data, forma=None, comprovante_id=None, observacao=None, usuario_id=None):
    """Registra o pagamento do saldo e marca a conta como paga (usado ao anexar comprovante)."""
    if not nota.pagamentos and (nota.valor_pago or ZERO) > 0 and nota.status != "Pendente":
        # valor pago registrado antes das baixas detalhadas
        db.session.add(Pagamento(nota=nota, valor=nota.valor_pago, data=nota.data_pagamento or nota.data_emissao,
                                 observacao="Valor já registrado antes das baixas", registrado_por_id=usuario_id))
    jaPago = sum((p.valor for p in nota.pagamentos), ZERO)
    saldo = (nota.valor or ZERO) - jaPago
    if saldo > 0:
        db.session.add(Pagamento(nota=nota, valor=saldo, data=data, forma=forma, observacao=observacao,
                                 comprovante_id=comprovante_id, registrado_por_id=usuario_id))
    nota.quitada = True
    db.session.flush()
    recalcular_situacao(nota)


@painel_bp.route("/")
@login_required
def visao_geral():
    hoje = hoje_sp()
    inicio_mes = hoje.replace(day=1)
    fim_mes = somar_meses(inicio_mes, 1) - timedelta(days=1)

    notas = Nota.query.filter(Nota.status != "Cancelado").all()
    abertas = [n for n in notas if n.em_aberto]

    def soma_saldo(lista):
        return sum((n.saldo_restante for n in lista), ZERO)

    pagar = [n for n in abertas if n.tipo == "saida"]
    receber = [n for n in abertas if n.tipo == "entrada"]
    atrasadas_pagar = [n for n in pagar if n.is_atrasada]
    vence_7 = [n for n in pagar if n.data_vencimento and hoje <= n.data_vencimento <= hoje + timedelta(days=7)]

    kpis = {
        "a_pagar": soma_saldo(pagar), "qtd_a_pagar": len(pagar),
        "atrasado": soma_saldo(atrasadas_pagar), "qtd_atrasado": len(atrasadas_pagar),
        "vence_7": soma_saldo(vence_7), "qtd_vence_7": len(vence_7),
        "pago_mes": sum((_pagamentos_no_periodo(n, inicio_mes, fim_mes) for n in notas if n.tipo == "saida"), ZERO),
        "recebido_mes": sum((_pagamentos_no_periodo(n, inicio_mes, fim_mes) for n in notas if n.tipo == "entrada"), ZERO),
        "a_receber": soma_saldo(receber), "qtd_a_receber": len(receber),
    }

    # Próximos vencimentos (30 dias) e atrasadas, das duas direções
    proximos = sorted(
        [n for n in abertas if n.data_vencimento and hoje <= n.data_vencimento <= hoje + timedelta(days=30)],
        key=lambda n: n.data_vencimento,
    )
    atrasadas = sorted([n for n in abertas if n.is_atrasada], key=lambda n: n.data_vencimento)

    # Gráfico 1: pago x recebido nos últimos 12 meses
    historico = OrderedDict()
    for i in range(11, -1, -1):
        ini = somar_meses(inicio_mes, -i)
        fim = somar_meses(ini, 1) - timedelta(days=1)
        historico[f"{MESES[ini.month - 1]}/{str(ini.year)[2:]}"] = (
            float(sum((_pagamentos_no_periodo(n, ini, fim) for n in notas if n.tipo == "saida"), ZERO)),
            float(sum((_pagamentos_no_periodo(n, ini, fim) for n in notas if n.tipo == "entrada"), ZERO)),
        )

    # Gráfico 2: o que vence nos próximos 6 meses (a pagar x a receber), com atrasadas no mês atual
    agenda = OrderedDict()
    for i in range(6):
        ini = somar_meses(inicio_mes, i)
        fim = somar_meses(ini, 1) - timedelta(days=1)
        def no_mes(n):
            return n.data_vencimento and (ini <= n.data_vencimento <= fim or (i == 0 and n.data_vencimento < ini))
        agenda[f"{MESES[ini.month - 1]}/{str(ini.year)[2:]}"] = (
            float(soma_saldo([n for n in pagar if no_mes(n)])),
            float(soma_saldo([n for n in receber if no_mes(n)])),
        )

    # O que precisa de atenção primeiro: prioridade + atraso + vencimento próximo (só contas a pagar)
    atencao = sorted([n for n in pagar if n.atencao >= 60 or (n.prioridade or 2) >= 3],
                     key=lambda n: (-n.atencao, n.data_vencimento or hoje))

    documentos = DocumentoEmpresa.query.filter(
        DocumentoEmpresa.data_validade.isnot(None),
        DocumentoEmpresa.data_validade <= hoje + timedelta(days=30),
    ).order_by(DocumentoEmpresa.data_validade).limit(8).all()

    return render_template(
        "visao_geral.html", hoje=hoje, kpis=kpis, proximos=proximos[:12], qtd_proximos=len(proximos),
        atrasadas=atrasadas[:12], qtd_atrasadas=len(atrasadas), documentos=documentos,
        atencao=atencao[:8], qtd_atencao=len(atencao),
        historico_labels=list(historico.keys()), historico_pago=[v[0] for v in historico.values()],
        historico_recebido=[v[1] for v in historico.values()],
        agenda_labels=list(agenda.keys()), agenda_pagar=[v[0] for v in agenda.values()],
        agenda_receber=[v[1] for v in agenda.values()],
    )


@painel_bp.route("/contas/<int:nota_id>")
@login_required
def detalhe(nota_id):
    nota = db.get_or_404(Nota, nota_id)
    historico = LogAuditoria.query.filter_by(referencia=f"nota:{nota.id}").order_by(LogAuditoria.criado_em.desc()).all()
    recorrentes = []
    if nota.grupo_recorrencia:
        recorrentes = Nota.query.filter_by(grupo_recorrencia=nota.grupo_recorrencia).order_by(Nota.data_vencimento).all()
    from flask import current_app
    return render_template(
        "detalhe_conta.html", nota=nota, historico=historico, recorrentes=recorrentes, hoje=hoje_sp(),
        formas=current_app.config["FORMAS_PAGAMENTO"],
    )


@painel_bp.route("/contas/<int:nota_id>/pagamentos", methods=["POST"])
@login_required
def registrar_pagamento(nota_id):
    from .notas import registrar_log, parse_data, parse_valor
    nota = db.get_or_404(Nota, nota_id)
    if not nota.pode_editar(current_user):
        abort(403)
    valor = parse_valor(request.form.get("valor"))
    if valor <= 0:
        flash("Informe o valor pago.", "danger")
        return redirect(url_for("painel.detalhe", nota_id=nota.id))
    try:
        comprovante = salvar_upload(request.files.get("comprovante"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("painel.detalhe", nota_id=nota.id))

    # Contas antigas marcadas como pagas sem baixas: a primeira baixa registra o que já constava
    if not nota.pagamentos and (nota.valor_pago or ZERO) > 0:
        db.session.add(Pagamento(nota=nota, valor=nota.valor_pago, data=nota.data_pagamento or nota.data_emissao,
                                 forma=None, observacao="Valor já registrado antes das baixas", registrado_por_id=current_user.id))
    pag = Pagamento(
        nota=nota, valor=valor, data=parse_data(request.form.get("data"), hoje_sp()),
        forma=request.form.get("forma") or None, observacao=(request.form.get("observacao") or "").strip() or None,
        comprovante_id=comprovante.id if comprovante else None, registrado_por_id=current_user.id,
    )
    db.session.add(pag)
    db.session.flush()
    # "Quitar a conta": com comprovante anexado e a opção marcada, a conta conta como paga
    if request.form.get("quitar") == "1":
        nota.quitada = True
    recalcular_situacao(nota)
    if comprovante and not nota.comprovante_id:
        nota.comprovante_id = comprovante.id
        nota.comprovante_nome_original = comprovante.nome_original
    db.session.commit()
    registrar_log("Registrou Pagamento", f"Doc #{nota.id}: {valor} em {pag.data.strftime('%d/%m/%Y')} ({pag.forma or '—'}) · status {nota.status}", referencia=f"nota:{nota.id}")
    flash(f"Baixa registrada. Situação: {nota.status}.", "success")
    return redirect(url_for("painel.detalhe", nota_id=nota.id))


@painel_bp.route("/contas/<int:nota_id>/pagamentos/<int:pag_id>/excluir", methods=["POST"])
@login_required
def excluir_pagamento(nota_id, pag_id):
    from .notas import registrar_log
    nota = db.get_or_404(Nota, nota_id)
    if not nota.pode_editar(current_user):
        abort(403)
    pag = db.get_or_404(Pagamento, pag_id)
    if pag.nota_id != nota.id:
        abort(404)
    comp_id = pag.comprovante_id
    descricao = f"Doc #{nota.id}: {pag.valor} de {pag.data.strftime('%d/%m/%Y')}"
    nota.pagamentos.remove(pag)
    db.session.delete(pag)
    nota.quitada = False  # remover uma baixa reabre a conta
    db.session.flush()
    if comp_id and comp_id != nota.comprovante_id:
        excluir_arquivo(comp_id)
    recalcular_situacao(nota)
    db.session.commit()
    registrar_log("Excluiu Pagamento", descricao + f" · status {nota.status}", referencia=f"nota:{nota.id}")
    flash("Baixa removida.", "info")
    return redirect(url_for("painel.detalhe", nota_id=nota.id))
