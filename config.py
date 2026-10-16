import os


class Config:
    """Configuracao da aplicacao.

    Em producao (Railway) as variaveis DATABASE_URL, SECRET_KEY e
    UPLOAD_FOLDER sao definidas no painel do projeto. Localmente, se nao
    existirem, caem em valores padrao (SQLite + pasta ./uploads) para
    facilitar testes na sua maquina antes do deploy.
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-chave-troque-em-producao")

    _db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
    # O Railway pode entregar "postgres://", "postgresql://" ou "postgresql+psycopg://"
    # (driver psycopg 3, que não está instalado). Qualquer que seja o formato,
    # usa o driver do requirements.txt: psycopg2.
    for _prefixo in ("postgres://", "postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if _db_url.startswith(_prefixo):
            _db_url = "postgresql+psycopg2://" + _db_url[len(_prefixo):]
            break
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Em producao, aponte para o caminho onde o Volume do Railway esta
    # montado, ex: /data/uploads
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    )

    # Endereço do painel administrativo (link "Voltar ao painel" no menu)
    PAINEL_URL = os.environ.get("PAINEL_URL", "https://apextechmetais.com.br/admin.html")

    MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB por arquivo
    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "heic"}

    CATEGORIAS = [
        "Conta de Luz",
        "Conta de Água",
        "Aluguel",
        "Impostos & Taxas",
        "Compra de Sucata / E-waste",
        "Venda de Materiais / Metais",
        "Frete & Logística",
        "Manutenção de Maquinário",
        "Folha / Salários",
        "Serviço",
        "Outro",
    ]

    TIPOS_DOCUMENTO = ["Boleto", "NF-e", "Contrato", "Foto", "Recibo", "Outro"]

    STATUS_FINANCEIRO = ["Pendente", "Parcial", "Pago", "Recebido", "Cancelado"]


    # Configurações de E-mail / SMTP para Notificações de Vencimento
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)


