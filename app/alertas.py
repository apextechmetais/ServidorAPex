"""Alertas de vencimento por e-mail.

- Resumo diário automático no horário configurado (padrão 08:00, horário de Brasília):
  contas atrasadas, que vencem hoje, que vencem nos próximos dias e documentos da empresa
  com validade vencendo.
- Envio pelo Resend (variável RESEND_API_KEY), que funciona no Railway; sem ela, usa SMTP (MAIL_*).
- Cada dia fica registrado em `alerta_envio` (dia único): com vários processos do gunicorn,
  só um consegue registrar o dia e enviar.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from datetime import timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from . import db
from .models import Nota, User, DocumentoEmpresa, Configuracao, AlertaEnvio
from .util import hoje_sp, agora_sp, brl

alertas_bp = Blueprint("alertas", __name__)

PADROES = {
    "alertas_ativos": "1",
    "alertas_horario": "08:00",
    "alertas_dias_antes": "7",          # contas que vencem nos próximos N dias
    "alertas_dias_validade": "30",      # documentos com validade nos próximos N dias
    "alertas_incluir_receber": "0",     # incluir contas a receber no resumo
    "alertas_destinatarios": "",        # e-mails extras, separados por vírgula
}


# ───────────────────────── configurações ─────────────────────────
def config_get(chave):
    item = db.session.get(Configuracao, chave)
    return item.valor if item and item.valor is not None else PADROES.get(chave, "")


def config_set(chave, valor):
    item = db.session.get(Configuracao, chave)
    if item is None:
        db.session.add(Configuracao(chave=chave, valor=valor))
    else:
        item.valor = valor


def _int(valor, padrao):
    try:
        return max(0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return padrao


def destinatarios():
    """Administradores com e-mail cadastrado + e-mails extras da configuração."""
    emails = [u.email.strip() for u in User.query.filter_by(is_admin=True, ativo=True).all() if u.email and u.email.strip()]
    extras = [e.strip() for e in config_get("alertas_destinatarios").replace(";", ",").split(",") if "@" in e]
    vistos, lista = set(), []
    for e in emails + extras:
        if e.lower() not in vistos:
            vistos.add(e.lower())
            lista.append(e)
    return lista


# ───────────────────────── envio de e-mail ─────────────────────────
def enviar_email(para, assunto, html):
    """Devolve (ok, mensagem). Resend se houver RESEND_API_KEY; senão SMTP."""
    if not para:
        return False, "Nenhum destinatário com e-mail cadastrado."
    chave = os.environ.get("RESEND_API_KEY", "").strip()
    remetente = os.environ.get("MAIL_FROM", "").strip() or current_app.config.get("MAIL_DEFAULT_SENDER") or "Apextech Metais <noreply@apextechmetais.com.br>"
    if chave:
        corpo = json.dumps({"from": remetente, "to": para, "subject": assunto, "html": html}).encode("utf-8")
        req = urllib.request.Request("https://api.resend.com/emails", data=corpo, method="POST", headers={
            "Authorization": f"Bearer {chave}", "Content-Type": "application/json", "User-Agent": "apextech-financeiro",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300, f"Enviado para {len(para)} destinatário(s)."
        except urllib.error.HTTPError as exc:
            return False, f"Resend recusou o envio ({exc.code}): {exc.read().decode('utf-8', 'ignore')[:200]}"
        except Exception as exc:
            return False, f"Falha ao contatar o Resend: {exc}"

    # SMTP (MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD...)
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    cfg = current_app.config
    if not cfg.get("MAIL_USERNAME") or not cfg.get("MAIL_PASSWORD"):
        return False, "E-mail não configurado: defina RESEND_API_KEY (recomendado) ou MAIL_USERNAME e MAIL_PASSWORD."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = cfg.get("MAIL_DEFAULT_SENDER") or cfg["MAIL_USERNAME"]
        msg["To"] = ", ".join(para)
        msg.attach(MIMEText(html, "html", "utf-8"))
        smtp = smtplib.SMTP(cfg.get("MAIL_SERVER"), cfg.get("MAIL_PORT", 587), timeout=15)
        if cfg.get("MAIL_USE_TLS", True):
            smtp.starttls()
        smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        smtp.sendmail(msg["From"], para, msg.as_string())
        smtp.quit()
        return True, f"Enviado para {len(para)} destinatário(s)."
    except Exception as exc:
        return False, f"Falha no SMTP: {exc}"


# ───────────────────────── conteúdo do resumo ─────────────────────────
def montar_resumo():
    """Separa o que precisa de atenção hoje. Devolve dict com listas e totais."""
    hoje = hoje_sp()
    dias_antes = _int(config_get("alertas_dias_antes"), 7)
    dias_validade = _int(config_get("alertas_dias_validade"), 30)
    tipos = ("saida", "entrada") if config_get("alertas_incluir_receber") == "1" else ("saida",)

    abertas = Nota.query.filter(Nota.status.in_(("Pendente", "Parcial")), Nota.tipo.in_(tipos), Nota.data_vencimento.isnot(None)).order_by(Nota.data_vencimento).all()
    # Mais importantes primeiro dentro de cada grupo
    def ordem(lista):
        return sorted(lista, key=lambda n: (-(n.prioridade or 2), n.data_vencimento))
    atrasadas = ordem([n for n in abertas if n.data_vencimento < hoje])
    hoje_lista = ordem([n for n in abertas if n.data_vencimento == hoje])
    proximas = ordem([n for n in abertas if hoje < n.data_vencimento <= hoje + timedelta(days=dias_antes)])
    documentos = DocumentoEmpresa.query.filter(
        DocumentoEmpresa.data_validade.isnot(None),
        DocumentoEmpresa.data_validade <= hoje + timedelta(days=dias_validade),
    ).order_by(DocumentoEmpresa.data_validade).all()
    return {
        "hoje": hoje, "dias_antes": dias_antes, "dias_validade": dias_validade,
        "atrasadas": atrasadas, "hoje_lista": hoje_lista, "proximas": proximas, "documentos": documentos,
        "vazio": not (atrasadas or hoje_lista or proximas or documentos),
    }


def html_resumo(r):
    base = os.environ.get("APP_URL", "").rstrip("/")

    def link(n):
        return f'{base}/contas/{n.id}' if base else ""

    def linhas_contas(lista, cor):
        if not lista:
            return '<p style="color:#9fb1a7;margin:6px 0 0;">Nada aqui.</p>'
        html = '<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:14px;">'
        for n in lista:
            d = (n.data_vencimento - r["hoje"]).days
            quando = "hoje" if d == 0 else (f"há {-d} dia(s)" if d < 0 else f"em {d} dia(s)")
            nome = n.cliente_fornecedor or n.categoria or "Sem fornecedor"
            url = link(n)
            nome_html = f'<a href="{url}" style="color:#F5F6F3;">{nome}</a>' if url else nome
            fluxo = "A receber" if n.tipo == "entrada" else "A pagar"
            prio = n.prioridade or 2
            if prio >= 3:
                cor_tag = "#ff6b6b" if prio == 4 else "#fb923c"
                nome_html += (f' <span style="display:inline-block;font-size:11px;font-weight:bold;color:{cor_tag};'
                              f'border:1px solid {cor_tag};border-radius:10px;padding:1px 7px;">{n.prioridade_nome.upper()}</span>')
            html += (
                f'<tr><td style="padding:8px 6px;border-bottom:1px solid #1d3b2c;border-left:3px solid {cor};">'
                f'<strong>{nome_html}</strong><br><span style="color:#9fb1a7;font-size:12px;">{fluxo} · {n.categoria or "—"} · vence {n.data_vencimento.strftime("%d/%m/%Y")} ({quando})</span></td>'
                f'<td style="padding:8px 6px;border-bottom:1px solid #1d3b2c;text-align:right;white-space:nowrap;"><strong>{brl(n.saldo_restante)}</strong></td></tr>'
            )
        return html + "</table>"

    def bloco(titulo, lista, cor):
        total = sum(n.saldo_restante for n in lista)
        return (f'<h3 style="margin:24px 0 0;font-size:16px;color:{cor};">{titulo} ({len(lista)}) — {brl(total)}</h3>'
                + linhas_contas(lista, cor))

    docs = ""
    if r["documentos"]:
        docs = f'<h3 style="margin:24px 0 0;font-size:16px;color:#38bdf8;">Documentos com validade até {r["dias_validade"]} dias ({len(r["documentos"])})</h3><table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:14px;">'
        for d in r["documentos"]:
            dias = d.dias_para_vencer
            quando = "venceu " + (f"há {-dias} dia(s)" if dias < 0 else "hoje") if dias <= 0 else f"vence em {dias} dia(s)"
            docs += (f'<tr><td style="padding:8px 6px;border-bottom:1px solid #1d3b2c;border-left:3px solid #38bdf8;"><strong>{d.titulo}</strong>'
                     f'<br><span style="color:#9fb1a7;font-size:12px;">{d.categoria} · validade {d.data_validade.strftime("%d/%m/%Y")} ({quando})</span></td></tr>')
        docs += "</table>"

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;background:#05130C;color:#F5F6F3;padding:24px;border-radius:12px;max-width:680px;">
      <h2 style="margin:0;font-size:20px;">Apextech Metais — vencimentos de {r['hoje'].strftime('%d/%m/%Y')}</h2>
      <p style="color:#9fb1a7;margin:6px 0 0;">Resumo do Financeiro: o que está atrasado, vence hoje e vence nos próximos {r['dias_antes']} dias.</p>
      {bloco('Atrasadas', r['atrasadas'], '#ff6b6b')}
      {bloco('Vencem hoje', r['hoje_lista'], '#ffcc00')}
      {bloco(f"Próximos {r['dias_antes']} dias", r['proximas'], '#25D07F')}
      {docs}
      {f'<p style="margin:24px 0 0;"><a href="{base}/" style="background:#25D07F;color:#05130C;padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:bold;">Abrir o Financeiro</a></p>' if base else ''}
      <p style="color:#6f8a7c;font-size:12px;margin-top:24px;">E-mail automático do Financeiro Apextech. Para mudar horário, antecedência ou destinatários, acesse Alertas por e-mail.</p>
    </div>"""


def enviar_resumo(forcar=False):
    """Monta e envia o resumo. Sem pendências, só envia se forcar=True (teste)."""
    r = montar_resumo()
    if r["vazio"] and not forcar:
        return True, "Nada vencendo: nenhum e-mail necessário hoje."
    partes = []
    if r["atrasadas"]:
        partes.append(f"{len(r['atrasadas'])} atrasada(s)")
    if r["hoje_lista"]:
        partes.append(f"{len(r['hoje_lista'])} vence(m) hoje")
    if r["proximas"]:
        partes.append(f"{len(r['proximas'])} nos próximos {r['dias_antes']} dias")
    assunto = "[Apextech] Vencimentos: " + (", ".join(partes) if partes else "nada pendente") + f" — {r['hoje'].strftime('%d/%m')}"
    return enviar_email(destinatarios(), assunto, html_resumo(r))


# ───────────────────────── agendador ─────────────────────────
def _verificar_envio_do_dia(app):
    with app.app_context():
        try:
            if config_get("alertas_ativos") != "1":
                return
            agora = agora_sp()
            hh, mm = (config_get("alertas_horario") or "08:00").split(":")[:2]
            if (agora.hour, agora.minute) < (int(hh), int(mm)):
                return
            if AlertaEnvio.query.filter_by(dia=agora.date()).first():
                return
            # Registra o dia antes de enviar: só um processo consegue (dia é único)
            registro = AlertaEnvio(dia=agora.date(), resultado="enviando")
            db.session.add(registro)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return
        except Exception as exc:
            db.session.rollback()
            app.logger.warning("Alertas: falha ao verificar o envio do dia: %s", exc)
            return
        ok, msg = enviar_resumo()
        registro.resultado = ("OK: " if ok else "ERRO: ") + msg
        db.session.commit()
        app.logger.info("Alertas do dia %s: %s", agora.date(), registro.resultado)


def iniciar_agendador(app):
    """Verifica a cada 5 minutos se já é hora do resumo do dia. Só roda no servidor web (gunicorn)."""
    no_servidor = "gunicorn" in os.path.basename(sys.argv[0]) or os.environ.get("ALERTAS_AGENDADOR") == "1"
    if app.testing or not no_servidor or os.environ.get("ALERTAS_AGENDADOR") == "0":
        return

    def laco():
        time.sleep(30)
        while True:
            _verificar_envio_do_dia(app)
            time.sleep(300)

    threading.Thread(target=laco, name="alertas-vencimento", daemon=True).start()


# ───────────────────────── telas ─────────────────────────
@alertas_bp.route("/alertas", methods=["GET", "POST"])
@login_required
def configurar():
    if not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        horario = request.form.get("alertas_horario", "08:00").strip()
        try:
            h, m = horario.split(":")
            assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59
        except Exception:
            flash("Horário inválido. Use o formato HH:MM.", "danger")
            return redirect(url_for("alertas.configurar"))
        config_set("alertas_ativos", "1" if request.form.get("alertas_ativos") else "0")
        config_set("alertas_horario", f"{int(h):02d}:{int(m):02d}")
        config_set("alertas_dias_antes", str(_int(request.form.get("alertas_dias_antes"), 7)))
        config_set("alertas_dias_validade", str(_int(request.form.get("alertas_dias_validade"), 30)))
        config_set("alertas_incluir_receber", "1" if request.form.get("alertas_incluir_receber") else "0")
        config_set("alertas_destinatarios", request.form.get("alertas_destinatarios", "").strip())
        db.session.commit()
        from .notas import registrar_log
        registrar_log("Configurou Alertas", f"Ativos: {config_get('alertas_ativos')} · {config_get('alertas_horario')} · {config_get('alertas_dias_antes')} dias")
        flash("Configuração dos alertas salva.", "success")
        return redirect(url_for("alertas.configurar"))

    cfg = {k: config_get(k) for k in PADROES}
    historico = AlertaEnvio.query.order_by(AlertaEnvio.dia.desc()).limit(15).all()
    return render_template(
        "alertas.html", cfg=cfg, destinatarios=destinatarios(), historico=historico, resumo=montar_resumo(),
        envio_resend=bool(os.environ.get("RESEND_API_KEY")), envio_smtp=bool(current_app.config.get("MAIL_USERNAME")),
    )


@alertas_bp.route("/alertas/enviar-agora", methods=["POST"])
@login_required
def enviar_agora():
    if not current_user.is_admin:
        abort(403)
    ok, msg = enviar_resumo(forcar=True)
    from .notas import registrar_log
    registrar_log("Enviou Alerta Manual", msg)
    flash(("Resumo enviado. " if ok else "Não foi possível enviar. ") + msg, "success" if ok else "danger")
    return redirect(request.referrer or url_for("alertas.configurar"))
