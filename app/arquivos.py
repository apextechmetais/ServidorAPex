"""Arquivos guardados no banco de dados.

O disco do Railway é apagado a cada publicação (a não ser que exista um volume): por isso toda
nota, comprovante e documento fica na tabela `arquivo`. Os arquivos antigos, salvos em disco,
são copiados para o banco ao iniciar o servidor.
"""
import mimetypes
import os

from flask import Blueprint, Response, abort, current_app
from flask_login import login_required, current_user

from . import db
from .models import Arquivo, Nota

arquivos_bp = Blueprint("arquivos", __name__)

# Abrem no navegador; o resto é baixado
EXIBIVEIS = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "text/plain")


def extensao(nome):
    return nome.rsplit(".", 1)[-1].lower() if "." in (nome or "") else ""


def extensao_permitida(nome):
    return extensao(nome) in current_app.config["ALLOWED_EXTENSIONS"]


def salvar_upload(arquivo_enviado):
    """Guarda um arquivo enviado pelo formulário no banco. Devolve o Arquivo (ainda sem commit) ou None."""
    if not arquivo_enviado or not arquivo_enviado.filename:
        return None
    if not extensao_permitida(arquivo_enviado.filename):
        raise ValueError("Formato não permitido: " + arquivo_enviado.filename)
    dados = arquivo_enviado.read()
    mimetype = arquivo_enviado.mimetype or mimetypes.guess_type(arquivo_enviado.filename)[0] or "application/octet-stream"
    arq = Arquivo(
        nome_original=arquivo_enviado.filename[:255],
        mimetype=mimetype,
        tamanho=len(dados),
        dados=dados,
        enviado_por_id=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(arq)
    db.session.flush()  # gera o id
    return arq


def excluir_arquivo(arquivo_id):
    if arquivo_id:
        arq = db.session.get(Arquivo, arquivo_id)
        if arq:
            db.session.delete(arq)


def resposta_arquivo(arq, baixar=False):
    nome = arq.nome_original.replace('"', "")
    disposicao = "attachment" if baixar or arq.mimetype not in EXIBIVEIS else "inline"
    resp = Response(arq.dados, mimetype=arq.mimetype)
    resp.headers["Content-Disposition"] = f'{disposicao}; filename="{nome}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@arquivos_bp.route("/arquivos/<int:arquivo_id>")
@arquivos_bp.route("/arquivos/<int:arquivo_id>/<acao>")
@login_required
def abrir(arquivo_id, acao=None):
    arq = db.session.get(Arquivo, arquivo_id)
    if not arq:
        abort(404)
    return resposta_arquivo(arq, baixar=(acao == "baixar"))


def mover_arquivos_do_disco_para_banco(app):
    """Copia para o banco os arquivos de notas que ainda estão só no disco. Pode rodar várias vezes."""
    pasta = app.config["UPLOAD_FOLDER"]
    movidos = 0
    try:
        notas = Nota.query.filter(
            db.or_(
                db.and_(Nota.arquivo_id.is_(None), Nota.arquivo_nome.isnot(None), Nota.arquivo_nome != ""),
                db.and_(Nota.comprovante_id.is_(None), Nota.comprovante_nome.isnot(None), Nota.comprovante_nome != ""),
            )
        ).all()
        for nota in notas:
            for campo_nome, campo_original, campo_id in (
                ("arquivo_nome", "arquivo_nome_original", "arquivo_id"),
                ("comprovante_nome", "comprovante_nome_original", "comprovante_id"),
            ):
                nome_disco = getattr(nota, campo_nome)
                if not nome_disco or getattr(nota, campo_id):
                    continue
                caminho = os.path.join(pasta, os.path.basename(nome_disco))
                if not os.path.isfile(caminho):
                    continue
                with open(caminho, "rb") as f:
                    dados = f.read()
                original = getattr(nota, campo_original) or nome_disco
                arq = Arquivo(
                    nome_original=original[:255],
                    mimetype=mimetypes.guess_type(original)[0] or "application/octet-stream",
                    tamanho=len(dados), dados=dados, enviado_por_id=nota.enviado_por_id,
                )
                db.session.add(arq)
                db.session.flush()
                setattr(nota, campo_id, arq.id)
                movidos += 1
        db.session.commit()
        if movidos:
            app.logger.info("%s arquivo(s) do disco copiados para o banco.", movidos)
    except Exception as exc:
        db.session.rollback()
        app.logger.warning("Não foi possível copiar arquivos do disco para o banco: %s", exc)
    return movidos
