from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from . import db
from .models import User

auth_bp = Blueprint("auth", __name__)


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Apenas administradores podem acessar essa página.", "danger")
            return redirect(url_for("painel.visao_geral"))
        return f(*args, **kwargs)

    return wrapper


import time

# Dicionário em memória para proteção contra Brute Force
# Formato: { "key": {"tentativas": int, "bloqueado_ate": float} }
TENTATIVAS_LOGIN = {}
MAX_TENTATIVAS = 5
TEMPO_BLOQUEIO_SEGUNDOS = 300  # 5 minutos


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("painel.visao_geral"))

    if request.method == "POST":
        from flask import current_app
        from .notas import registrar_log

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip_cliente = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip_cliente and "," in ip_cliente:
            ip_cliente = ip_cliente.split(",")[0].strip()

        chave_bloqueio = f"{username.lower()}:{ip_cliente}"
        agora = time.time()

        # Verificar se esta temporariamente bloqueado por forca bruta
        info_tentativas = TENTATIVAS_LOGIN.get(chave_bloqueio, {"tentativas": 0, "bloqueado_ate": 0})
        
        if info_tentativas["bloqueado_ate"] > agora:
            tempo_restante = int(info_tentativas["bloqueado_ate"] - agora)
            minutos = tempo_restante // 60
            segundos = tempo_restante % 60
            msg_tempo = f"{minutos} min e {segundos} s" if minutos > 0 else f"{segundos} segundos"
            flash(f"Muitas tentativas incorretas. Conta bloqueada temporariamente. Aguarde {msg_tempo} para tentar novamente.", "danger")
            return render_template("login.html")

        # Se o tempo de bloqueio já expirou, reseta o contador
        if info_tentativas["bloqueado_ate"] > 0 and info_tentativas["bloqueado_ate"] <= agora:
            TENTATIVAS_LOGIN[chave_bloqueio] = {"tentativas": 0, "bloqueado_ate": 0}
            info_tentativas = TENTATIVAS_LOGIN[chave_bloqueio]

        # 1. Tenta autenticacao local
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.ativo:
            # Login com sucesso: reseta contador de erros
            TENTATIVAS_LOGIN.pop(chave_bloqueio, None)
            login_user(user, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("painel.visao_geral"))

        # 2. Fallback: tenta ApexAmostra (se URL configurada)
        apex_url = current_app.config.get("APEX_AMOSTRA_URL", "")
        if apex_url:
            from .apex_auth import autenticar_apex, obter_ou_criar_shadow_user
            resultado = autenticar_apex(apex_url, username, password)
            if resultado:
                TENTATIVAS_LOGIN.pop(chave_bloqueio, None)
                shadow = obter_ou_criar_shadow_user(
                    db, User,
                    username=username,
                    nome=resultado["nome"],
                    is_admin=resultado["is_admin"],
                )
                login_user(shadow, remember=True)
                next_page = request.args.get("next")
                return redirect(next_page or url_for("painel.visao_geral"))

        # Login falhou: incrementa contador de tentativas incorretas
        tentativas_atuais = info_tentativas["tentativas"] + 1
        if tentativas_atuais >= MAX_TENTATIVAS:
            bloqueado_ate = agora + TEMPO_BLOQUEIO_SEGUNDOS
            TENTATIVAS_LOGIN[chave_bloqueio] = {"tentativas": tentativas_atuais, "bloqueado_ate": bloqueado_ate}
            registrar_log("Bloqueio de Força Bruta", f"Usuário '{username}' bloqueado por 5 minutos após {MAX_TENTATIVAS} tentativas erradas de login (IP: {ip_cliente}).")
            flash("Muitas tentativas incorretas consecutivas (5/5). Sua conta foi temporariamente bloqueada por 5 minutos por segurança.", "danger")
        else:
            TENTATIVAS_LOGIN[chave_bloqueio] = {"tentativas": tentativas_atuais, "bloqueado_ate": 0}
            restantes = MAX_TENTATIVAS - tentativas_atuais
            flash(f"Usuário ou senha inválidos. Restam {restantes} tentativa(s) antes do bloqueio temporário.", "danger")

        return render_template("login.html")

    return render_template("login.html")



@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/usuarios")
@login_required
@admin_required
def usuarios():
    todos = User.query.order_by(User.nome).all()
    return render_template("usuarios.html", usuarios=todos)


@auth_bp.route("/usuarios/novo", methods=["POST"])
@login_required
@admin_required
def novo_usuario():
    username = request.form.get("username", "").strip()
    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    is_admin = bool(request.form.get("is_admin"))

    if not username or not nome or not password:
        flash("Preencha todos os campos obrigatórios.", "danger")
        return redirect(url_for("auth.usuarios"))

    if User.query.filter_by(username=username).first():
        flash("Já existe um usuário com esse login.", "danger")
        return redirect(url_for("auth.usuarios"))

    user = User(username=username, nome=nome, email=email, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)

    db.session.commit()
    flash(f"Usuário '{nome}' criado com sucesso.", "success")
    return redirect(url_for("auth.usuarios"))


@auth_bp.route("/usuarios/<int:user_id>/alternar", methods=["POST"])
@login_required
@admin_required
def alternar_usuario(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Você não pode desativar seu próprio usuário.", "warning")
        return redirect(url_for("auth.usuarios"))
    user.ativo = not user.ativo
    db.session.commit()
    estado = "ativado" if user.ativo else "desativado"
    flash(f"Usuário '{user.nome}' {estado}.", "info")
    return redirect(url_for("auth.usuarios"))
