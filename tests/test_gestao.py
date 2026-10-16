"""Testes da gestão de contas, documentos e alertas.

Rodar:  python -m unittest discover -s tests -v
Usa um SQLite temporário; nada é enviado por e-mail (o envio é substituído nos testes).
"""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest import mock

PASTA = tempfile.mkdtemp(prefix="apex-testes-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(PASTA, "teste.db").replace("\\", "/")
os.environ["UPLOAD_FOLDER"] = os.path.join(PASTA, "uploads")
os.environ["SECRET_KEY"] = "teste"
os.environ["ADMIN_PASSWORD"] = "Senha#Teste1"
os.environ.pop("RESEND_API_KEY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402
from app.models import Nota, Pagamento, DocumentoEmpresa, Arquivo, AlertaEnvio, User  # noqa: E402
from app.util import hoje_sp  # noqa: E402

PDF = b"%PDF-1.4\n%teste\n"


class GestaoTestes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.c = cls.app.test_client()
        r = cls.c.post("/login", data={"username": "admin", "password": "Senha#Teste1"})
        assert r.status_code == 302, "login do admin do ambiente falhou"

    def nova_conta(self, **campos):
        dados = {"tipo": "saida", "tipo_documento": "Boleto", "categoria": "Conta de Luz", "cliente_fornecedor": "Enel",
                 "valor": "1.000,00", "valor_pago": "0", "data_emissao": hoje_sp().isoformat(),
                 "data_vencimento": (hoje_sp() + timedelta(days=5)).isoformat(), "status": "Pendente"}
        dados.update(campos)
        r = self.c.post("/notas/nova", data=dados, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        nota_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
        with self.app.app_context():
            return db.session.get(Nota, nota_id)

    def test_01_telas_abrem(self):
        for url in ["/", "/contas", "/notas/nova", "/documentos", "/documentos/novo", "/alertas", "/dre", "/auditoria", "/usuarios"]:
            self.assertEqual(self.c.get(url).status_code, 200, url)
        for filtro in ["a_pagar", "a_receber", "atrasadas", "hoje", "7dias", "30dias", "pagas"]:
            self.assertEqual(self.c.get("/contas?situacao=" + filtro).status_code, 200, filtro)

    def test_02_conta_sem_anexo_e_detalhe(self):
        nota = self.nova_conta(cliente_fornecedor="Sabesp", categoria="Conta de Água")
        self.assertFalse(nota.tem_arquivo)
        html = self.c.get(f"/contas/{nota.id}").get_data(as_text=True)
        self.assertIn("Sabesp", html)
        self.assertIn("Dar baixa", html)
        self.assertIn("R$ 1.000,00", html)

    def test_03_anexo_fica_no_banco_e_abre(self):
        nota = self.nova_conta(arquivo=(io.BytesIO(PDF), "boleto.pdf"))
        self.assertTrue(nota.arquivo_id)
        r = self.c.get(f"/notas/{nota.id}/arquivo", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, PDF)
        self.assertEqual(r.mimetype, "application/pdf")

    def test_04_repetir_todo_mes(self):
        nota = self.nova_conta(cliente_fornecedor="Imobiliária", repetir="mensal", repetir_meses="12",
                               data_vencimento="2026-01-31")
        with self.app.app_context():
            grupo = Nota.query.filter_by(grupo_recorrencia=nota.grupo_recorrencia).order_by(Nota.data_vencimento).all()
        self.assertEqual(len(grupo), 12)
        self.assertEqual(str(grupo[1].data_vencimento), "2026-02-28")  # 31/01 + 1 mês = último dia de fevereiro
        self.assertEqual(str(grupo[-1].data_vencimento), "2026-12-31")

    def test_05_baixas_parcial_total_e_remocao(self):
        nota = self.nova_conta(valor="1.000,00")
        url = f"/contas/{nota.id}/pagamentos"
        self.c.post(url, data={"valor": "400,00", "data": hoje_sp().isoformat(), "forma": "PIX",
                               "comprovante": (io.BytesIO(PDF), "pix.pdf")}, content_type="multipart/form-data")
        with self.app.app_context():
            n = db.session.get(Nota, nota.id)
            self.assertEqual(n.status, "Parcial")
            self.assertEqual(n.saldo_restante, Decimal("600.00"))
            self.assertTrue(n.comprovante_id)
        self.c.post(url, data={"valor": "600,00", "data": hoje_sp().isoformat(), "forma": "Boleto"}, content_type="multipart/form-data")
        with self.app.app_context():
            n = db.session.get(Nota, nota.id)
            self.assertEqual(n.status, "Pago")
            self.assertEqual(n.saldo_restante, Decimal("0"))
            pag_id = n.pagamentos[-1].id
        self.c.post(f"/contas/{nota.id}/pagamentos/{pag_id}/excluir")
        with self.app.app_context():
            n = db.session.get(Nota, nota.id)
            self.assertEqual(n.status, "Parcial")
            self.assertEqual(n.valor_pago, Decimal("400.00"))

    def test_06_atrasada_aparece_nos_filtros_e_na_visao_geral(self):
        nota = self.nova_conta(cliente_fornecedor="Fornecedor Atrasado", data_vencimento=(hoje_sp() - timedelta(days=3)).isoformat())
        # o nome também aparece no filtro "Cliente / Fornecedor": confere pelo link da conta na lista
        link = f'/contas/{nota.id}"'
        self.assertIn(link, self.c.get("/contas?situacao=atrasadas").get_data(as_text=True))
        self.assertNotIn(link, self.c.get("/contas?situacao=7dias").get_data(as_text=True))
        self.assertIn("Fornecedor Atrasado", self.c.get("/").get_data(as_text=True))
        self.assertEqual(nota.dias_para_vencer, -3)

    def test_07_documentos_da_empresa(self):
        r = self.c.post("/documentos/novo", data={
            "titulo": "Alvará de funcionamento", "categoria": "Alvarás e Licenças", "orgao": "Prefeitura",
            "data_validade": (hoje_sp() + timedelta(days=10)).isoformat(), "arquivo": (io.BytesIO(PDF), "alvara.pdf"),
        }, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.c.post("/documentos/novo", data={"titulo": "Contrato social", "categoria": "Documentos Societários",
                                              "arquivo": (io.BytesIO(PDF), "contrato.pdf")}, content_type="multipart/form-data")
        self.assertIn("Alvará", self.c.get("/documentos?situacao=vencendo").get_data(as_text=True))
        self.assertNotIn("Contrato social", self.c.get("/documentos?situacao=vencendo").get_data(as_text=True))
        self.assertIn("Contrato social", self.c.get("/documentos?busca=contrato").get_data(as_text=True))
        self.assertIn("Contrato social", self.c.get("/documentos?situacao=sem_validade").get_data(as_text=True))
        with self.app.app_context():
            doc = DocumentoEmpresa.query.filter_by(titulo="Contrato social").first()
            arq_id = doc.arquivo_id
        self.c.post(f"/documentos/{doc.id}/excluir")
        with self.app.app_context():
            self.assertIsNone(db.session.get(Arquivo, arq_id), "arquivo do documento excluído deveria sair do banco")

    def test_08_resumo_de_alertas(self):
        from app.alertas import montar_resumo, html_resumo
        self.nova_conta(cliente_fornecedor="Vence Hoje Ltda", data_vencimento=hoje_sp().isoformat())
        with self.app.app_context():
            r = montar_resumo()
            nomes_hoje = [n.cliente_fornecedor for n in r["hoje_lista"]]
            self.assertIn("Vence Hoje Ltda", nomes_hoje)
            self.assertTrue(r["atrasadas"])
            html = html_resumo(r)
            self.assertIn("Vence Hoje Ltda", html)
            self.assertIn("Alvará de funcionamento", html)

    def test_09_resumo_automatico_sai_uma_vez_por_dia(self):
        from app import alertas
        with self.app.app_context():
            alertas.config_set("alertas_horario", "00:00")
            db.session.commit()
        with mock.patch.object(alertas, "enviar_resumo", return_value=(True, "ok")) as enviar:
            alertas._verificar_envio_do_dia(self.app)
            alertas._verificar_envio_do_dia(self.app)
        self.assertEqual(enviar.call_count, 1)
        with self.app.app_context():
            self.assertEqual(AlertaEnvio.query.filter_by(dia=hoje_sp()).count(), 1)

    def test_10_sem_email_configurado_avisa(self):
        from app.alertas import enviar_email
        with self.app.app_context():
            ok, msg = enviar_email(["a@b.com"], "teste", "<p>x</p>")
        self.assertFalse(ok)
        self.assertIn("RESEND_API_KEY", msg)

    def test_11_arquivo_antigo_do_disco_vai_para_o_banco(self):
        from app.arquivos import mover_arquivos_do_disco_para_banco
        os.makedirs(self.app.config["UPLOAD_FOLDER"], exist_ok=True)
        with open(os.path.join(self.app.config["UPLOAD_FOLDER"], "antigo.pdf"), "wb") as f:
            f.write(PDF)
        with self.app.app_context():
            admin = User.query.filter_by(username="admin").first()
            n = Nota(tipo="saida", valor=Decimal("10"), data_emissao=hoje_sp(), status="Pendente",
                     arquivo_nome="antigo.pdf", arquivo_nome_original="nota-antiga.pdf", enviado_por_id=admin.id)
            db.session.add(n)
            db.session.commit()
            self.assertEqual(mover_arquivos_do_disco_para_banco(self.app), 1)
            self.assertEqual(mover_arquivos_do_disco_para_banco(self.app), 0)  # não duplica
            arq = db.session.get(Arquivo, db.session.get(Nota, n.id).arquivo_id)
            self.assertEqual(arq.dados, PDF)

    def test_12_visitante_nao_ve_nada(self):
        anonimo = self.app.test_client()
        for url in ["/", "/contas", "/documentos", "/alertas", "/arquivos/1"]:
            r = anonimo.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
