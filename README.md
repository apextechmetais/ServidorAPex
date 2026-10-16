# 🛡️ Apextech Metais — Servidor de Gestão Financeira & Reciclagem de Eletrônicos

Sistema web corporativo completo para gestão de **Contas a Pagar**, **Contas a Receber**, **DRE Simplificado**, **Automação por IA/OCR**, **Alertas por E-mail**, **Emissão de Recibos em PDF**, **Auditoria** e **Segurança Avançada**. 

Desenvolvido para alta performance e implantado no **Railway** com PostgreSQL + Armazenamento Persistente.

---

## 🚀 Funcionalidades Detalhadas

### 🎯 1. Contas a Pagar & Contas a Receber
- **Gestão Completa de Fluxo de Caixa**: Registro e acompanhamento de Entradas (Vendas de Cobre, Metais, Placas e E-waste) e Saídas (Conta de Luz, Água, Impostos, Aluguel, Compra de Sucata, Frete, Folha).
- **Datas de Emissão, Vencimento e Pagamento**: Filtros avançados por intervalos de datas e destaque automático visual em vermelho animado para contas **ATRASADAS**.
- **Comprovantes Anexos (PIX / Bancários)**: Suporte ao anexo da nota fiscal principal e do comprovante bancário individual.

### 💳 2. Quitação / Baixa Parcial & Parcelamento
- **Amortização Parcial de Contas (`valor_pago`)**: Possibilidade de dar baixa em frações do valor total do boleto/nota.
- **Cálculo Automático do Saldo Restante (`saldo_restante`)**: Exibição do valor que ainda falta quitar (`Falta: R$ X,XX`) e atualização automática de status para **`PARCIAL`**.

### 🤖 3. Leitura Automática por IA / OCR
- **Preenchimento Inteligente**: Ao selecionar a foto ou PDF de um boleto/nota fiscal, o sistema executa leitura via expressões regulares e extração de PDF, preenchendo automaticamente o **Valor R$** e a **Data de Vencimento** no formulário.

### 📈 4. DRE Simplificado & Fechamento Mensal (`/dre`)
- **Demonstrativo de Resultado do Exercício**: Apuração mês a mês de Receitas Realizadas x Despesas Realizadas = **Lucro Líquido / Prejuízo**.
- **Seletor de Ano Fiscal**: Comparativo de desempenho anual acumulado com indicadores visuais de Superávit / Déficit.

### 📄 5. Emissão de Recibos em PDF & Exportação Excel
- **Gerador de Recibos em PDF (`/notas/<id>/recibo-pdf`)**: Impressão com 1 clique de recibo timbrado oficial com a marca **Apextech Metais**, incluindo dados da transação e campo de assinatura.
- **Exportação para Excel (`.xlsx`)**: Planilha estilizada nas cores corporativas respeitando todos os filtros aplicados na tela.

### ✉️ 6. Alertas Automáticos por E-mail (SMTP)
- **Varredura Diária de Pendências**: Notificação via e-mail corporativo em HTML com as contas a pagar que vencem HOJE e as pendências em ATRASO.
- **Disparo com 1 Clique**: Botão de Alertas no Dashboard e envio automatizado aos administradores cadastrados.

### 🔒 7. Segurança Avançada & Governança
- **Proteção contra Força Bruta (Brute Force)**: Bloqueio automático de **5 minutos** após 5 erros seguidos de senha por Usuário/IP.
- **Visualização de Senha (Ícone de Olho `👁️`)**: Alternância dinâmica de visibilidade nos campos de senha.
- **Log de Auditoria (`/auditoria`)**: Rastreamento de ações (Criação, Edição, Exclusão, Disparo de E-mails) com nome do usuário, timestamp e IP real.
- **Cabeçalhos de Segurança HTTP**: Proteção ativa com `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff` e CSRF Tokens.

---

## 🛠️ Tecnologias Utilizadas

- **Core**: Python 3.12, Flask 3.0, SQLAlchemy 3.1, Flask-Login, Flask-WTF.
- **Banco de Dados**: PostgreSQL (Railway) / SQLite (Desenvolvimento Local).
- **Processamento de Arquivos & PDF**: `pypdf`, `Pillow`, `reportlab`, `openpyxl`.
- **Frontend & Interface**: HTML5, Vanilla CSS3 (Custom Dark Theme), Bootstrap 5.3, FontAwesome 6, Chart.js.

---

## 🖥️ Como Rodar Localmente

```bash
# 1. Clonar o repositório
git clone https://github.com/devjohnnydev/ServidorAPex.git
cd ServidorAPex

# 2. Criar ambiente virtual Python
python -m venv .venv
.venv\Scripts\activate        # No Linux/Mac: source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Inicializar Banco de Dados e Usuário Admin
flask --app wsgi init-db
flask --app wsgi criar-admin

# 5. Executar servidor local
python wsgi.py
# Acessar em: http://localhost:5000
```

---

## ☁️ Deploy no Railway

1. Conecte o repositório GitHub ao seu projeto no Railway.
2. Adicione o banco de dados **PostgreSQL** no painel do Railway.
3. Crie um **Volume** em `/data` e defina `UPLOAD_FOLDER=/data/uploads`.
4. Defina as variáveis de ambiente opcionais para disparo de e-mails:
   ```env
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USE_TLS=true
   MAIL_USERNAME=seu_email@apextech.com.br
   MAIL_PASSWORD=sua_senha_de_app
   ```

---

## ✒️ Marca & Identidade Visual
**Apextech Metais** — *Sistema de Gestão Financeira & Reciclagem de Eletrônicos*

