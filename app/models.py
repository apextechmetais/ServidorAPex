from datetime import datetime
from decimal import Decimal
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


    def set_password(self, senha):
        self.password_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.password_hash, senha)

    def get_id(self):
        # Flask-Login exige string
        return str(self.id)


class Nota(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero_nota = db.Column(db.String(50))
    tipo = db.Column(db.String(20), nullable=False)  # "entrada" ou "saida"
    tipo_documento = db.Column(db.String(40), default="Outro")  # Boleto, NF-e, Contrato, Foto, Recibo, Outro
    categoria = db.Column(db.String(60))
    cliente_fornecedor = db.Column(db.String(150))
    valor = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    valor_pago = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    data_emissao = db.Column(db.Date, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=True)
    data_pagamento = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="Pendente")  # Pendente, Pago, Recebido, Parcial, Cancelado
    descricao = db.Column(db.Text)


    arquivo_nome = db.Column(db.String(255), nullable=False)  # nome salvo em disco
    arquivo_nome_original = db.Column(db.String(255), nullable=False)

    comprovante_nome = db.Column(db.String(255), nullable=True)
    comprovante_nome_original = db.Column(db.String(255), nullable=True)

    enviado_por_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    enviado_por = db.relationship("User", backref="notas")

    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def saldo_restante(self):
        if self.status in ("Pago", "Recebido"):
            return Decimal("0")
        v = self.valor or Decimal("0")
        vp = self.valor_pago or Decimal("0")
        res = v - vp
        return res if res > 0 else Decimal("0")

    @property
    def is_atrasada(self):
        if self.status in ("Pendente", "Parcial") and self.data_vencimento:
            return self.data_vencimento < datetime.utcnow().date()
        return False


    def pode_editar(self, user):
        return user.is_admin or self.enviado_por_id == user.id


class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class LogAuditoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    usuario_nome = db.Column(db.String(120), nullable=False)
    acao = db.Column(db.String(80), nullable=False)  # Criou, Editou, Excluiu, Baixou Pagamento, etc.
    detalhes = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("User", backref="logs_auditoria")



