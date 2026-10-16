from datetime import datetime
from decimal import Decimal
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .util import hoje_sp


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

    # Arquivos guardados no banco (os campos *_nome acima são do armazenamento antigo em disco)
    arquivo_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=True)
    comprovante_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=True)
    # Contas repetidas todo mês compartilham o mesmo grupo
    grupo_recorrencia = db.Column(db.String(32), nullable=True)

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
    def em_aberto(self):
        return self.status in ("Pendente", "Parcial")

    @property
    def is_atrasada(self):
        if self.em_aberto and self.data_vencimento:
            return self.data_vencimento < hoje_sp()
        return False

    @property
    def dias_para_vencer(self):
        """Dias até o vencimento (negativo = atrasada). None se não está em aberto ou não tem vencimento."""
        if not self.em_aberto or not self.data_vencimento:
            return None
        return (self.data_vencimento - hoje_sp()).days

    @property
    def tem_arquivo(self):
        return bool(self.arquivo_id or self.arquivo_nome)

    @property
    def tem_comprovante(self):
        return bool(self.comprovante_id or self.comprovante_nome)


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
    referencia = db.Column(db.String(40), nullable=True, index=True)  # ex.: "nota:12", "doc:3"
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("User", backref="logs_auditoria")


class Arquivo(db.Model):
    """Arquivo guardado no banco de dados (não se perde quando o servidor é republicado)."""
    id = db.Column(db.Integer, primary_key=True)
    nome_original = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False, default="application/octet-stream")
    tamanho = db.Column(db.Integer, nullable=False, default=0)
    dados = db.Column(db.LargeBinary, nullable=False)
    enviado_por_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class Pagamento(db.Model):
    """Cada baixa (total ou parcial) registrada numa conta."""
    id = db.Column(db.Integer, primary_key=True)
    nota_id = db.Column(db.Integer, db.ForeignKey("nota.id", ondelete="CASCADE"), nullable=False, index=True)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    data = db.Column(db.Date, nullable=False)
    forma = db.Column(db.String(40), nullable=True)
    observacao = db.Column(db.Text, nullable=True)
    comprovante_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=True)
    registrado_por_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    nota = db.relationship("Nota", backref=db.backref("pagamentos", order_by="Pagamento.data", cascade="all, delete-orphan"))
    registrado_por = db.relationship("User")


class DocumentoEmpresa(db.Model):
    """Arquivo digital da empresa: contratos, alvarás, certidões, documentos societários etc."""
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    categoria = db.Column(db.String(80), nullable=False, default="Outros")
    numero = db.Column(db.String(80), nullable=True)
    orgao = db.Column(db.String(150), nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    data_emissao = db.Column(db.Date, nullable=True)
    data_validade = db.Column(db.Date, nullable=True)
    arquivo_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=False)
    enviado_por_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    arquivo = db.relationship("Arquivo")
    enviado_por = db.relationship("User")

    @property
    def dias_para_vencer(self):
        if not self.data_validade:
            return None
        return (self.data_validade - hoje_sp()).days

    @property
    def situacao(self):
        """vencido | vencendo (até 30 dias) | valido | sem_validade"""
        d = self.dias_para_vencer
        if d is None:
            return "sem_validade"
        if d < 0:
            return "vencido"
        if d <= 30:
            return "vencendo"
        return "valido"

    def pode_editar(self, user):
        return user.is_admin or self.enviado_por_id == user.id


class Configuracao(db.Model):
    chave = db.Column(db.String(80), primary_key=True)
    valor = db.Column(db.Text, nullable=True)


class AlertaEnvio(db.Model):
    """Um registro por dia em que o resumo automático saiu (evita envio duplicado entre processos)."""
    id = db.Column(db.Integer, primary_key=True)
    dia = db.Column(db.Date, nullable=False, unique=True)
    enviado_em = db.Column(db.DateTime, default=datetime.utcnow)
    resultado = db.Column(db.Text, nullable=True)

