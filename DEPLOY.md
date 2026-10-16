# Deploy do Sistema de Notas Fiscais (ServidorApex) no Railway

Repositório: `https://github.com/devjohnnydev/ServidorApex.git`

Projeto independente (Flask), sem relação de build com o site/ERP em Node
(`ApexAmostra`). A única ligação entre os dois é um link no `admin.html`
do site apontando para a URL pública deste app.

---

## 1. Enviar o código para o GitHub

Na pasta do projeto (depois de extrair/clonar):

```bash
git init
git branch -M main
git add .
git commit -m "chore: commit inicial - sistema de notas fiscais"
git remote add origin https://github.com/devjohnnydev/ServidorApex.git
git push -u origin main
```

(Se o repositório remoto já tiver algum commit, ex. um README criado pela
interface do GitHub, use `git pull --rebase origin main` antes do push.)

## 2. Criar o projeto no Railway

1. Acesse [railway.app](https://railway.app) → **New Project**.
2. Escolha **Deploy from GitHub repo** → selecione `devjohnnydev/ServidorApex`.
3. Como o repositório já é só o Flask, o Railway detecta sozinho o
   `requirements.txt` e o `Procfile` na raiz — não precisa mexer em
   Root Directory.

## 3. Adicionar Postgres

1. No projeto → **New** → **Database** → **Add PostgreSQL**.
2. O Railway cria a variável `DATABASE_URL` automaticamente e injeta no
   serviço web (mesmo projeto).

## 4. Adicionar o Volume (armazenamento dos arquivos)

1. No serviço web → **Settings** → **Volumes** → **New Volume**.
2. Mount path: `/data`

## 5. Variáveis de ambiente

| Variável | Valor |
|---|---|
| `SECRET_KEY` | gere com `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | já vem do Postgres (passo 3) |
| `UPLOAD_FOLDER` | `/data/uploads` |

## 6. Deploy e domínio

1. O build dispara sozinho após configurar as variáveis.
2. **Settings** → **Networking** → **Generate Domain** (ou Custom Domain
   com CNAME, ex. `notas.apextech.com.br`).

## 7. Inicializar banco e criar o admin

```bash
npm install -g @railway/cli
railway login
railway link          # selecione o projeto/serviço do ServidorApex
railway run flask --app wsgi init-db
railway run flask --app wsgi criar-admin
```

## 8. Testar

Login com o admin criado, enviar uma nota de teste (foto ou PDF), conferir
no dashboard, e criar os logins dos funcionários em **Usuários**.

## 9. Ligar ao site (admin.html do ApexAmostra)

No `admin.html`, já existe o link pronto no menu (seção "Gestão Apextech"):

```html
<a href="https://SEU-APP.up.railway.app" ...>
```

Troque `https://SEU-APP.up.railway.app` pela URL real do passo 6, depois:

```bash
git add admin.html
git commit -m "chore: atualiza link do sistema de notas fiscais"
git push origin main
```

(esse commit é no repositório do **ApexAmostra**, não no do ServidorApex)

## Checklist

- [ ] `git push` no repo ServidorApex feito
- [ ] Projeto criado no Railway a partir do repo
- [ ] Postgres criado (`DATABASE_URL` configurada)
- [ ] Volume em `/data`, `UPLOAD_FOLDER=/data/uploads`
- [ ] `SECRET_KEY` definida
- [ ] Domínio gerado
- [ ] `init-db` + `criar-admin` executados
- [ ] Testado (login, upload, usuários)
- [ ] Link atualizado no `admin.html` do ApexAmostra
