"""Documentos da empresa: contratos, alvarás, certidões, documentos societários, RH, seguros etc."""
from datetime import timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user

from . import db
from .models import DocumentoEmpresa, User
from .util import hoje_sp
from .arquivos import salvar_upload, excluir_arquivo

documentos_bp = Blueprint("documentos", __name__)


def _categorias():
    usadas = [r[0] for r in db.session.query(DocumentoEmpresa.categoria).distinct().all() if r[0]]
    return list(dict.fromkeys(current_app.config["CATEGORIAS_DOCUMENTOS"] + sorted(usadas)))


@documentos_bp.route("/documentos")
@login_required
def lista():
    from .notas import parse_data
    hoje = hoje_sp()
    q = DocumentoEmpresa.query
    busca = request.args.get("busca", "").strip()
    categoria = request.args.get("categoria", "")
    situacao = request.args.get("situacao", "")
    enviado_por = request.args.get("enviado_por", "")
    validade_ate = parse_data(request.args.get("validade_ate", ""))
    emissao_de = parse_data(request.args.get("emissao_de", ""))
    emissao_ate = parse_data(request.args.get("emissao_ate", ""))

    if busca:
        like = f"%{busca}%"
        q = q.filter(db.or_(DocumentoEmpresa.titulo.ilike(like), DocumentoEmpresa.numero.ilike(like),
                            DocumentoEmpresa.orgao.ilike(like), DocumentoEmpresa.descricao.ilike(like)))
    if categoria:
        q = q.filter(DocumentoEmpresa.categoria == categoria)
    if enviado_por.isdigit():
        q = q.filter(DocumentoEmpresa.enviado_por_id == int(enviado_por))
    if situacao == "vencido":
        q = q.filter(DocumentoEmpresa.data_validade < hoje)
    elif situacao == "vencendo":
        q = q.filter(DocumentoEmpresa.data_validade >= hoje, DocumentoEmpresa.data_validade <= hoje + timedelta(days=30))
    elif situacao == "valido":
        q = q.filter(DocumentoEmpresa.data_validade > hoje + timedelta(days=30))
    elif situacao == "sem_validade":
        q = q.filter(DocumentoEmpresa.data_validade.is_(None))
    if validade_ate:
        q = q.filter(DocumentoEmpresa.data_validade <= validade_ate)
    if emissao_de:
        q = q.filter(DocumentoEmpresa.data_emissao >= emissao_de)
    if emissao_ate:
        q = q.filter(DocumentoEmpresa.data_emissao <= emissao_ate)

    ordem = request.args.get("ordem", "validade")
    if ordem == "titulo":
        q = q.order_by(DocumentoEmpresa.titulo)
    elif ordem == "recentes":
        q = q.order_by(DocumentoEmpresa.criado_em.desc())
    else:
        q = q.order_by(DocumentoEmpresa.data_validade.asc().nullslast(), DocumentoEmpresa.titulo)
    documentos = q.all()

    todos = DocumentoEmpresa.query.all()
    contagem = {
        "total": len(todos),
        "vencido": sum(1 for d in todos if d.situacao == "vencido"),
        "vencendo": sum(1 for d in todos if d.situacao == "vencendo"),
        "valido": sum(1 for d in todos if d.situacao == "valido"),
        "sem_validade": sum(1 for d in todos if d.situacao == "sem_validade"),
    }
    return render_template("documentos.html", documentos=documentos, filtros=request.args, categorias_doc=_categorias(),
                           contagem=contagem, usuarios=User.query.order_by(User.nome).all())


def _preencher(doc):
    from .notas import parse_data
    doc.titulo = request.form.get("titulo", "").strip()[:200]
    categoria = request.form.get("categoria_nova", "").strip() or request.form.get("categoria", "").strip()
    doc.categoria = (categoria or "Outros")[:80]
    doc.numero = request.form.get("numero", "").strip()[:80] or None
    doc.orgao = request.form.get("orgao", "").strip()[:150] or None
    doc.descricao = request.form.get("descricao", "").strip() or None
    doc.data_emissao = parse_data(request.form.get("data_emissao"))
    doc.data_validade = parse_data(request.form.get("data_validade"))


@documentos_bp.route("/documentos/novo", methods=["GET", "POST"])
@login_required
def novo():
    from .notas import registrar_log
    if request.method == "POST":
        doc = DocumentoEmpresa(enviado_por_id=current_user.id)
        _preencher(doc)
        if not doc.titulo:
            flash("Informe o título do documento.", "danger")
            return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())
        try:
            arq = salvar_upload(request.files.get("arquivo"))
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())
        if not arq:
            flash("Selecione o arquivo do documento.", "danger")
            return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())
        doc.arquivo_id = arq.id
        db.session.add(doc)
        db.session.commit()
        registrar_log("Arquivou Documento", f"{doc.titulo} ({doc.categoria})", referencia=f"doc:{doc.id}")
        flash("Documento guardado.", "success")
        return redirect(url_for("documentos.lista"))
    return render_template("documento_form.html", doc=None, categorias_doc=_categorias())


@documentos_bp.route("/documentos/<int:doc_id>/editar", methods=["GET", "POST"])
@login_required
def editar(doc_id):
    from .notas import registrar_log
    doc = db.get_or_404(DocumentoEmpresa, doc_id)
    if not doc.pode_editar(current_user):
        abort(403)
    if request.method == "POST":
        _preencher(doc)
        if not doc.titulo:
            flash("Informe o título do documento.", "danger")
            return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())
        try:
            novo_arq = salvar_upload(request.files.get("arquivo"))
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())
        if novo_arq:
            antigo = doc.arquivo_id
            doc.arquivo_id = novo_arq.id
            db.session.flush()
            excluir_arquivo(antigo)
        db.session.commit()
        registrar_log("Editou Documento", f"{doc.titulo} ({doc.categoria})" + (" · arquivo substituído" if novo_arq else ""), referencia=f"doc:{doc.id}")
        flash("Documento atualizado.", "success")
        return redirect(url_for("documentos.lista"))
    return render_template("documento_form.html", doc=doc, categorias_doc=_categorias())


@documentos_bp.route("/documentos/<int:doc_id>/excluir", methods=["POST"])
@login_required
def excluir(doc_id):
    from .notas import registrar_log
    doc = db.get_or_404(DocumentoEmpresa, doc_id)
    if not doc.pode_editar(current_user):
        abort(403)
    titulo, arq_id = doc.titulo, doc.arquivo_id
    db.session.delete(doc)
    db.session.flush()
    excluir_arquivo(arq_id)
    db.session.commit()
    registrar_log("Excluiu Documento da Empresa", titulo, referencia=f"doc:{doc_id}")
    flash("Documento excluído.", "info")
    return redirect(url_for("documentos.lista"))
