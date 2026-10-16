"""Testes: quitar com comprovante, prioridades e métricas de gastos.

Rodar:  python -m unittest discover -s tests -v
"""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal

PASTA = tempfile.mkdtemp(prefix="apex-testes-prio-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(PASTA, "teste.db").replace("\\", "/")
os.environ["UPLOAD_FOLDER"] = os.path.join(PASTA, "uploads")
os.environ["SECRET_KEY"] = "teste"
os.environ["ADMIN_PASSWORD"] = "Senha#Teste1"
os.environ.pop("RESEND_API_KEY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402
from app.models import Nota  # noqa: E402
from app.util import hoje_sp  # noqa: E402

PDF = b"%PDF-1.4\n%comprovante\n"


class PrioridadeGastosTestes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Banco próprio desta classe (o outro arquivo de testes usa outro SQLite)
        from config import Config
        Config.SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.c = cls.app.test_client()
        assert cls.c.post("/login", data={"username": "admin", "password": "Senha#Teste1"}).status_code == 302

    def conta(self, **campos):
        dados = {"tipo": "saida", "tipo_documento": "Boleto", "categoria": "Impostos & Taxas", "cliente_fornecedor": "Receita",
                 "valor": "1.000,00", "valor_pago": "0", "data_emissao": hoje_sp().isoformat(),
                 "data_vencimento": (hoje_sp() + timedelta(days=20)).isoformat(), "status": "Pendente", "prioridade": "2"}
        dados.update(campos)
        r = self.c.post("/notas/nova", data=dados, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            return db.session.get(Nota, int(r.headers["Location"].rstrip("/").split("/")[-1]))

    def test_01_baixa_com_quitar_fica_paga_mesmo_com_desconto(self):
        n = self.conta(cliente_fornecedor="Acordo Ltda")
        self.c.post(f"/contas/{n.id}/pagamentos", data={"valor": "900,00", "data": hoje_sp().isoformat(), "forma": "PIX",
                                                        "quitar": "1", "comprovante": (io.BytesIO(PDF), "pix.pdf")},
                    content_type="multipart/form-data")
        with self.app.app_context():
            n2 = db.session.get(Nota, n.id)
            self.assertEqual(n2.status, "Pago")
            self.assertTrue(n2.quitada)
            self.assertEqual(n2.valor_pago, Decimal("900.00"))
            self.assertTrue(n2.comprovante_id)
            pag_id = n2.pagamentos[0].id
        # remover a baixa reabre a conta
        self.c.post(f"/contas/{n.id}/pagamentos/{pag_id}/excluir")
        with self.app.app_context():
            n3 = db.session.get(Nota, n.id)
            self.assertEqual(n3.status, "Pendente")
            self.assertFalse(n3.quitada)

    def test_02_sem_quitar_valor_menor_fica_parcial(self):
        n = self.conta(cliente_fornecedor="Parcial Ltda")
        self.c.post(f"/contas/{n.id}/pagamentos", data={"valor": "300,00", "data": hoje_sp().isoformat()}, content_type="multipart/form-data")
        with self.app.app_context():
            self.assertEqual(db.session.get(Nota, n.id).status, "Parcial")

    def test_03_nova_conta_com_comprovante_ja_paga(self):
        n = self.conta(cliente_fornecedor="Paga no Cadastro", ja_paga="1", comprovante=(io.BytesIO(PDF), "comp.pdf"))
        with self.app.app_context():
            n2 = db.session.get(Nota, n.id)
            self.assertEqual(n2.status, "Pago")
            self.assertEqual(len(n2.pagamentos), 1)
            self.assertEqual(n2.pagamentos[0].valor, Decimal("1000.00"))
            self.assertEqual(n2.pagamentos[0].comprovante_id, n2.comprovante_id)

    def test_04_editar_anexando_comprovante_marca_paga(self):
        n = self.conta(cliente_fornecedor="Edita e Paga")
        dados = {"tipo": "saida", "tipo_documento": "Boleto", "categoria": "Impostos & Taxas", "cliente_fornecedor": "Edita e Paga",
                 "valor": "1.000,00", "valor_pago": "0", "data_emissao": hoje_sp().isoformat(),
                 "data_vencimento": (hoje_sp() + timedelta(days=20)).isoformat(), "status": "Pendente", "prioridade": "3",
                 "ja_paga": "1", "comprovante": (io.BytesIO(PDF), "comp.pdf")}
        self.assertEqual(self.c.post(f"/notas/{n.id}/editar", data=dados, content_type="multipart/form-data").status_code, 302)
        with self.app.app_context():
            n2 = db.session.get(Nota, n.id)
            self.assertEqual(n2.status, "Pago")
            self.assertEqual(n2.prioridade, 3)

    def test_05_prioridade_filtro_ordem_e_atencao(self):
        critica = self.conta(cliente_fornecedor="DAS Crítico", prioridade="4", valor="50,00",
                             data_vencimento=(hoje_sp() + timedelta(days=25)).isoformat())
        normal = self.conta(cliente_fornecedor="Normal Longe", prioridade="2", data_vencimento=(hoje_sp() + timedelta(days=25)).isoformat())
        lista = self.c.get("/contas?situacao=prioritarias").get_data(as_text=True)
        self.assertIn(f'/contas/{critica.id}"', lista)
        self.assertNotIn(f'/contas/{normal.id}"', lista)
        self.assertIn(f'/contas/{critica.id}"', self.c.get("/contas?prioridade=4").get_data(as_text=True))
        ordenada = self.c.get("/contas?situacao=a_pagar&ordem=atencao").get_data(as_text=True)
        self.assertLess(ordenada.index(f'/contas/{critica.id}"'), ordenada.index(f'/contas/{normal.id}"'))
        visao = self.c.get("/").get_data(as_text=True)
        self.assertIn("Precisam de atenção", visao)
        self.assertIn("DAS Crítico", visao)

    def test_06_recorrencia_herda_prioridade(self):
        n = self.conta(cliente_fornecedor="Folha", prioridade="4", repetir="mensal", repetir_meses="3")
        with self.app.app_context():
            grupo = Nota.query.filter_by(grupo_recorrencia=db.session.get(Nota, n.id).grupo_recorrencia).all()
            self.assertEqual({g.prioridade for g in grupo}, {4})

    def test_07_metricas_de_gastos(self):
        n = self.conta(cliente_fornecedor="Gasto Hoje", categoria="Frete & Logística", valor="250,00")
        self.c.post(f"/contas/{n.id}/pagamentos", data={"valor": "250,00", "data": hoje_sp().isoformat(), "quitar": "1"},
                    content_type="multipart/form-data")
        from app.gastos import movimentos, soma
        with self.app.app_context():
            movs = movimentos("saida")
            hoje = hoje_sp()
            total_hoje = soma(movs, hoje, hoje)
        self.assertGreaterEqual(total_hoje, Decimal("250.00"))
        for periodo in ["hoje", "semana", "7dias", "mes", "30dias", "3meses", "6meses", "12meses", "ano"]:
            r = self.c.get("/gastos?periodo=" + periodo)
            self.assertEqual(r.status_code, 200, periodo)
        html = self.c.get("/gastos?periodo=hoje").get_data(as_text=True)
        self.assertIn("Gasto Hoje", html)
        self.assertIn("Frete &amp; Logística", html)
        de = (hoje_sp() - timedelta(days=60)).isoformat()
        self.assertEqual(self.c.get(f"/gastos?periodo=personalizado&de={de}&ate={hoje_sp().isoformat()}").status_code, 200)
        self.assertEqual(self.c.get("/gastos?fluxo=entrada&periodo=ano").status_code, 200)

    def test_08_alerta_mostra_prioridade(self):
        from app.alertas import montar_resumo, html_resumo
        self.conta(cliente_fornecedor="Energia Crítica", prioridade="4", data_vencimento=hoje_sp().isoformat())
        with self.app.app_context():
            r = montar_resumo()
            self.assertEqual(r["hoje_lista"][0].cliente_fornecedor, "Energia Crítica")
            self.assertIn("CRÍTICA", html_resumo(r))


if __name__ == "__main__":
    unittest.main(verbosity=2)
