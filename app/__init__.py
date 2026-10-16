import os
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para continuar."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)

    from . import models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        return models.User.query.get(int(user_id))

    from .auth import auth_bp
    from .notas import notas_bp
    from .setup import setup_bp  # primeiro admin: só com a variável SETUP_TOKEN definida

    from .painel import painel_bp
    from .documentos import documentos_bp
    from .alertas import alertas_bp, iniciar_agendador
    from .arquivos import arquivos_bp
    from .gastos import gastos_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(painel_bp)
    app.register_blueprint(documentos_bp)
    app.register_blueprint(alertas_bp)
    app.register_blueprint(arquivos_bp)
    app.register_blueprint(gastos_bp)
    app.register_blueprint(setup_bp)

    with app.app_context():
        db.create_all()
        _migrar_colunas(db)
        _inicializar_categorias(app, db)
        _garantir_admin_do_ambiente(db)
        _mover_arquivos_com_trava(app, db)

    iniciar_agendador(app)

    register_cli(app)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.context_processor
    def inject_globals():

        from .models import Categoria
        todas_categorias = app.config["CATEGORIAS"]
        try:
            cats_db = [c.nome for c in Categoria.query.order_by(Categoria.nome).all()]
            todas_categorias = list(dict.fromkeys(app.config["CATEGORIAS"] + cats_db))
        except Exception:
            db.session.rollback()
        from datetime import date
        return {
            "categorias": todas_categorias,
            "tipos_documento": app.config["TIPOS_DOCUMENTO"],
            "status_financeiro": app.config["STATUS_FINANCEIRO"],
            "painel_url": app.config.get("PAINEL_URL", ""),
            "ano_atual": date.today().year,
        }

    @app.template_filter("sp")
    def hora_sp(valor, formato="%d/%m/%Y %H:%M"):
        """Data/hora gravada em UTC mostrada no horário de Brasília."""
        if not valor:
            return "—"
        from datetime import timezone
        from .util import FUSO
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(FUSO).strftime(formato)

    @app.template_filter("brl")
    def formatar_brl(valor):
        """Valor em reais no formato brasileiro: R$ 48.320,90 (negativo: -R$ 1.234,00)."""
        try:
            numero = float(valor or 0)
        except (TypeError, ValueError):
            return valor
        texto = f"{abs(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return ("-R$ " if numero < 0 else "R$ ") + texto

    return app



def _mover_arquivos_com_trava(app, db):
    """Copia para o banco os arquivos que estão no disco. Com vários processos do gunicorn,
    a trava do PostgreSQL (presa a uma conexão própria) deixa só um fazer a cópia."""
    from sqlalchemy import text
    from .arquivos import mover_arquivos_do_disco_para_banco
    if db.engine.dialect.name != "postgresql":
        mover_arquivos_do_disco_para_banco(app)
        return
    try:
        with db.engine.connect() as conn:
            if not conn.execute(text("SELECT pg_try_advisory_lock(918273)")).scalar():
                return
            try:
                mover_arquivos_do_disco_para_banco(app)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(918273)"))
    except Exception as exc:
        app.logger.warning("Cópia dos arquivos para o banco não executada: %s", exc)


def _garantir_admin_do_ambiente(db):
    """Acesso de administrador definido nas variáveis de ambiente (Railway).

    ADMIN_PASSWORD (obrigatória para ativar), ADMIN_USERNAME (padrão "admin") e ADMIN_NOME.
    A cada início o usuário é criado, ou tem a senha atualizada para a do ambiente,
    e fica ativo e administrador. Sem ADMIN_PASSWORD nada é feito.
    """
    import logging
    from .models import User

    senha = os.environ.get("ADMIN_PASSWORD", "")
    if not senha:
        return
    username = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
    nome = os.environ.get("ADMIN_NOME", "Administrador").strip() or "Administrador"
    try:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, nome=nome, is_admin=True, ativo=True)
            db.session.add(user)
        elif user.check_password(senha) and user.is_admin and user.ativo:
            return  # já está como no ambiente
        user.is_admin = True
        user.ativo = True
        user.set_password(senha)
        db.session.commit()
        logging.getLogger(__name__).info("Administrador '%s' configurado a partir das variáveis de ambiente.", username)
    except Exception:
        # Com mais de um processo (gunicorn) iniciando juntos, outro pode ter criado o usuário primeiro
        db.session.rollback()


def _inicializar_categorias(app, db):
    """Insere as categorias padrao no banco se a tabela estiver vazia."""
    from .models import Categoria
    try:
        if Categoria.query.count() == 0:
            for cat_nome in app.config["CATEGORIAS"]:
                db.session.add(Categoria(nome=cat_nome))
            db.session.commit()
    except Exception:
        db.session.rollback()




def _migrar_colunas(db):
    """Adiciona colunas novas a tabelas ja existentes (safe migration)."""
    from sqlalchemy import text, inspect
    inspector = inspect(db.engine)
    
    colunas_nota = []
    try:
        colunas_nota = [c["name"] for c in inspector.get_columns("nota")]
    except Exception:
        pass

    novas_colunas_nota = [
        ("tipo_documento", "ALTER TABLE nota ADD COLUMN tipo_documento VARCHAR(40) DEFAULT 'Outro'"),
        ("data_vencimento", "ALTER TABLE nota ADD COLUMN data_vencimento DATE"),
        ("data_pagamento", "ALTER TABLE nota ADD COLUMN data_pagamento DATE"),
        ("comprovante_nome", "ALTER TABLE nota ADD COLUMN comprovante_nome VARCHAR(255)"),
        ("comprovante_nome_original", "ALTER TABLE nota ADD COLUMN comprovante_nome_original VARCHAR(255)"),
        ("status", "ALTER TABLE nota ADD COLUMN status VARCHAR(20) DEFAULT 'Pendente'"),
        ("valor_pago", "ALTER TABLE nota ADD COLUMN valor_pago NUMERIC(12,2) DEFAULT 0"),
        ("arquivo_id", "ALTER TABLE nota ADD COLUMN arquivo_id INTEGER"),
        ("comprovante_id", "ALTER TABLE nota ADD COLUMN comprovante_id INTEGER"),
        ("grupo_recorrencia", "ALTER TABLE nota ADD COLUMN grupo_recorrencia VARCHAR(32)"),
        ("prioridade", "ALTER TABLE nota ADD COLUMN prioridade INTEGER NOT NULL DEFAULT 2"),
        ("quitada", "ALTER TABLE nota ADD COLUMN quitada BOOLEAN NOT NULL DEFAULT FALSE"),
    ]

    for col_nome, sql_cmd in novas_colunas_nota:
        if col_nome not in colunas_nota:
            try:
                db.session.execute(text(sql_cmd))
                db.session.commit()
            except Exception:
                db.session.rollback()

    try:
        colunas_log = [c["name"] for c in inspector.get_columns("log_auditoria")]
        if colunas_log and "referencia" not in colunas_log:
            db.session.execute(text("ALTER TABLE log_auditoria ADD COLUMN referencia VARCHAR(40)"))
            db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        colunas_user = [c["name"] for c in inspector.get_columns("user")]
        if "email" not in colunas_user:
            db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN email VARCHAR(120)"))
            db.session.commit()
    except Exception:
        db.session.rollback()




def register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Cria as tabelas do banco de dados."""
        with app.app_context():
            db.create_all()
        click.echo("Banco de dados inicializado.")

    @app.cli.command("criar-admin")
    @click.option("--username", prompt=True)
    @click.option("--nome", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def criar_admin(username, nome, password):
        """Cria (ou promove) um usuario administrador."""
        from .models import User

        with app.app_context():
            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(username=username, nome=nome, is_admin=True)
                user.set_password(password)
                db.session.add(user)
            else:
                user.nome = nome
                user.is_admin = True
                user.set_password(password)
            db.session.commit()
        click.echo(f"Administrador '{username}' pronto.")
