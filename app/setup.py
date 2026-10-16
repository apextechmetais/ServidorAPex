"""
Criação do primeiro administrador em produção, sem precisar do Shell do Railway.

Segurança:
- Só funciona se a variável SETUP_TOKEN estiver definida no Railway (não há código padrão).
- Gera uma senha aleatória e mostra uma única vez.
- Só cria o administrador se ainda não existir nenhum: nunca troca a senha de quem já existe.

Uso: defina SETUP_TOKEN no Railway e acesse https://SEU-APP/setup/<SETUP_TOKEN>.
Depois de entrar, apague a variável SETUP_TOKEN para desligar a rota.
"""
import os
import secrets

from flask import Blueprint, jsonify, abort
from . import db
from .models import User

setup_bp = Blueprint("setup", __name__)


@setup_bp.route("/setup/<token>")
def setup(token):
    esperado = os.environ.get("SETUP_TOKEN", "").strip()
    # Sem SETUP_TOKEN definido a rota não existe; código errado também responde 404
    if not esperado or not secrets.compare_digest(token, esperado):
        abort(404)

    if User.query.filter_by(is_admin=True).first():
        return jsonify({
            "status": "ja_configurado",
            "aviso": "Já existe um administrador. Nenhuma senha foi alterada. Apague a variável SETUP_TOKEN."
        })

    senha = secrets.token_urlsafe(12)
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        admin = User(username="admin", nome="Administrador", is_admin=True, ativo=True)
        db.session.add(admin)
    else:
        admin.is_admin = True
        admin.ativo = True
    admin.set_password(senha)
    db.session.commit()

    return jsonify({
        "status": "ok",
        "login": "admin",
        "senha": senha,
        "aviso": "Anote a senha agora: ela não será mostrada de novo. Depois de entrar, apague a variável SETUP_TOKEN no Railway."
    })
