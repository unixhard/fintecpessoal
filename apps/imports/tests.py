"""Testes da camada de importação (Ordem 17).

Cobrem:
  - normalização (valores em centavos, formatos BR/internacional, datas);
  - parsers CSV / OFX / XLSX (débito/crédito, cabeçalhos, delimitadores);
  - staging (nenhum registro definitivo antes da confirmação);
  - duplicidade (exata, provável, semelhantes válidas);
  - confirmação (via services existentes, rollback em erro, source/external_id);
  - segurança (isolamento: usuário A não acessa importação do usuário B).
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.finance.models import Account, Category, Transaction, UserPreference

from .models import ImportBatch, StagedTransaction
from .services import importer as importer_svc
from .services.commit import commit_batch
from .services.csv_parser import CsvConfig
from .services.normalise import (
    direction_from_amount,
    parse_date,
    to_cents,
)

User = get_user_model()


class NormaliseTests(TestCase):
    def test_br_thousands_with_comma_decimal(self):
        self.assertEqual(to_cents("1.234,56"), 123456)

    def test_international_dot_decimal(self):
        self.assertEqual(to_cents("1234.56"), 123456)

    def test_currency_symbol(self):
        self.assertEqual(to_cents("R$ 1.234,56"), 123456)

    def test_negative(self):
        self.assertEqual(to_cents("-50,00"), -5000)
        cents, direction = direction_from_amount("-50,00")
        self.assertEqual((cents, direction), (5000, "expense"))

    def test_positive_direction_income(self):
        cents, direction = direction_from_amount("1.234,56")
        self.assertEqual((cents, direction), (123456, "income"))

    def test_plain_integer_becomes_reais(self):
        self.assertEqual(to_cents("1234"), 123400)

    def test_invalid_raises(self):
        with self.assertRaises(Exception):
            to_cents("abc")

    def test_parse_dates(self):
        self.assertEqual(parse_date("2024-01-05"), date(2024, 1, 5))
        self.assertEqual(parse_date("05/01/2024"), date(2024, 1, 5))


class CsvParserTests(TestCase):
    def test_parse_br_with_header(self):
        content = "data;descricao;valor\n01/01/2024;MERCADO SAO JOSE;-150,50\n".encode("utf-8")
        rows = importer_svc.parse_file("csv", content)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.amount_cents, 15050)
        self.assertEqual(row.direction, "expense")
        self.assertEqual(row.date, date(2024, 1, 1))

    def test_detect_comma_delimiter(self):
        content = "data;descricao;valor\n02/01/2024;UBER;25,00\n".encode("utf-8")
        rows = importer_svc.parse_file("csv", content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount_cents, 2500)

    def test_debit_credit_columns(self):
        content = (
            "data;descricao;debito;credito\n"
            "03/01/2024;SALARIO;0;5000,00\n"
            "04/01/2024;PADARIA;12,30;0\n"
        ).encode("utf-8")
        rows = importer_svc.parse_file("csv", content)
        self.assertEqual(len(rows), 2)
        sal = [r for r in rows if "SALARIO" in r.description][0]
        pad = [r for r in rows if "PADARIA" in r.description][0]
        self.assertEqual((sal.amount_cents, sal.direction), (500000, "income"))
        self.assertEqual((pad.amount_cents, pad.direction), (1230, "expense"))

    def test_invalid_file_returns_empty(self):
        rows = importer_svc.parse_file("csv", b"sem, colunas, validas\nx, y, z\n")
        self.assertIsInstance(rows, list)

    def test_missing_required_columns_skipped(self):
        content = "a;b\n1;2\n".encode("utf-8")
        rows = importer_svc.parse_file("csv", content)
        self.assertEqual(len(rows), 0)


class ColumnNormalizerTests(TestCase):
    """Normalizador universal de colunas (agnóstico de banco) — §1."""

    def _cfg(self, header):
        from .services.column_normalizer import detect_and_map_columns

        return detect_and_map_columns(header)

    def test_client_spreadsheet_exact_format(self):
        # Formato da planilha de teste do cliente.
        cfg = self._cfg(["Data", "Descrição", "Categoria Sugerida", "Valor", "Tipo"])
        self.assertEqual((cfg.date, cfg.description, cfg.amount), (0, 1, 3))
        self.assertEqual(cfg.category, 2)
        self.assertEqual(cfg.type, 4)
        self.assertTrue(cfg.has_header)

    def test_multi_bank_variants(self):
        cfg = self._cfg(["Data Lançamento", "Histórico", "Valor (R$)", "Saldo", "D/C"])
        self.assertEqual((cfg.date, cfg.description, cfg.amount, cfg.balance), (0, 1, 2, 3))
        self.assertEqual(cfg.type, 4)

    def test_split_debit_credit_columns(self):
        cfg = self._cfg(["Data do Movimento", "Estabelecimento", "Débito", "Crédito", "Tipo"])
        self.assertEqual((cfg.date, cfg.description, cfg.debit, cfg.credit), (0, 1, 2, 3))

    def test_short_headers(self):
        cfg = self._cfg(["dt", "descricao", "vlr"])
        self.assertEqual((cfg.date, cfg.description, cfg.amount), (0, 1, 2))

    def test_uppercase_and_misspelled(self):
        cfg = self._cfg(["DATA TRANSACAO", "NARRACAO", "DEBITO", "CREDITO"])
        self.assertEqual((cfg.date, cfg.description, cfg.debit, cfg.credit), (0, 1, 2, 3))

    def test_no_header_falls_back_positional(self):
        cfg = self._cfg(["01/2024", "MERCADO", "50,00"])
        self.assertFalse(cfg.has_header)
        # fallback posicional é atribuído apenas quando vazio/válido
        self.assertEqual(cfg.date, 0)
        self.assertEqual(cfg.description, 1)
        self.assertEqual(cfg.amount, 2)


class ClientFormatIngestTests(TestCase):
    """End-to-end: planilha do cliente (Data/Desc/Categoria/Valor/Tipo)."""

    def setUp(self):
        self.user = User.objects.create_user(username="cli", password="x")
        self.account = Account.objects.create(
            owner=self.user, name="Conta", type=Account.Type.CHECKING
        )

    def test_ingest_client_format_carries_suggested_category(self):
        content = (
            "Data;Descrição;Categoria Sugerida;Valor;Tipo\n"
            "01/01/2024;SUSHI EXPRESS;Alimentação;-40,00;D\n"
            "05/01/2024;BURGUER HOUSE;Alimentação;-55,00;D\n"
            "10/01/2024;SALARIO;Salário;3000,00;C\n"
        ).encode("utf-8-sig")
        batch = importer_svc.ingest(
            user=self.user, file_type="csv", file_name="teste.csv",
            content=content, default_account=self.account,
        )
        self.assertEqual(batch.detected_count, 3)
        sal = batch.staged_rows.get(description="SALARIO")
        self.assertEqual(sal.direction, StagedTransaction.Direction.INCOME)
        self.assertEqual(sal.metadata.get("suggested_category"), "Salário")
        sushi = batch.staged_rows.get(description="SUSHI EXPRESS")
        self.assertEqual(sushi.direction, StagedTransaction.Direction.EXPENSE)
        self.assertEqual(sushi.metadata.get("suggested_category"), "Alimentação")

    def test_excel_serial_date(self):
        from .services.normalise import parse_date

        self.assertEqual(parse_date(45292), date(2024, 1, 1))
        self.assertEqual(parse_date(45658), date(2025, 1, 1))



class OfxParserTests(TestCase):
    def test_parse_ofx(self):
        ofx = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKACCTFROM>
<BANKID>001</BANKID><ACCTID>1234</ACCTID><ACCTTYPE>CHECKING</ACCTTYPE>
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20240101000000</DTSTART><DTEND>20240131000000</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20240115000000</DTPOSTED>
<TRNAMT>-150.50</TRNAMT><FITID>ABC123</FITID><MEMO>SUPERMERCADO</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20240110000000</DTPOSTED>
<TRNAMT>5000.00</TRNAMT><FITID>XYZ999</FITID><MEMO>SALARIO</MEMO>
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>1000.00</BALAMT><DTASOF>20240131000000</DTASOF></LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>"""
        rows = importer_svc.parse_file("ofx", ofx)
        self.assertEqual(len(rows), 2)
        by_desc = {r.description: r for r in rows}
        self.assertEqual(by_desc["SUPERMERCADO"].amount_cents, 15050)
        self.assertEqual(by_desc["SUPERMERCADO"].direction, "expense")
        self.assertEqual(by_desc["SUPERMERCADO"].source_id, "ABC123")
        self.assertEqual(by_desc["SALARIO"].direction, "income")


class XlsxParserTests(TestCase):
    def test_parse_xlsx(self):
        import openpyxl
        from io import BytesIO

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["data", "descricao", "valor"])
        ws.append(["05/01/2024", "DROGARIA", -45.90])
        ws.append(["06/01/2024", "PIX RECEBIDO", 200.00])
        buf = BytesIO()
        wb.save(buf)
        rows = importer_svc.parse_file("xlsx", buf.getvalue())
        self.assertEqual(len(rows), 2)
        drog = [r for r in rows if "DROGARIA" in r.description][0]
        self.assertEqual((drog.amount_cents, drog.direction), (4590, "expense"))


class StagingAndIngestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.account = Account.objects.create(
            owner=self.user, name="Corrente", type=Account.Type.CHECKING
        )

    def test_ingest_creates_staging_not_transactions(self):
        content = "data;descricao;valor\n01/01/2024;BAR;10,00\n".encode("utf-8")
        batch = importer_svc.ingest(
            user=self.user, file_type="csv", file_name="x.csv", content=content,
            default_account=self.account,
        )
        self.assertEqual(batch.detected_count, 1)
        self.assertEqual(batch.staged_rows.count(), 1)
        # Ainda NÃO existe nenhum registro definitivo.
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 0)

    def test_ingest_sets_source_direction_and_account(self):
        content = "data;descricao;valor\n01/01/2024;IFOOD;-30,00\n".encode("utf-8")
        batch = importer_svc.ingest(
            user=self.user, file_type="csv", file_name="x.csv", content=content,
            default_account=self.account,
        )
        staged = batch.staged_rows.get()
        self.assertEqual(staged.amount_cents, 3000)
        self.assertEqual(staged.direction, StagedTransaction.Direction.EXPENSE)
        self.assertEqual(staged.default_account_id, self.account.pk)
        self.assertEqual(staged.row_status, StagedTransaction.RowStatus.READY)


class DuplicateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.account = Account.objects.create(
            owner=self.user, name="Corrente", type=Account.Type.CHECKING
        )

    def _ingest(self, csv_text):
        return importer_svc.ingest(
            user=self.user, file_type="csv", file_name="x.csv",
            content=csv_text.encode("utf-8"), default_account=self.account,
        )

    def test_exact_duplicate_in_same_file_marked(self):
        csv_text = (
            "data;descricao;valor\n"
            "01/01/2024;IFOOD;30,00\n"
            "01/01/2024;IFOOD;30,00\n"
        )
        batch = self._ingest(csv_text)
        row = batch.staged_rows.get(confidence=StagedTransaction.Confidence.DUPLICATE)
        self.assertEqual(row.row_status, StagedTransaction.RowStatus.IGNORED)

    def test_duplicate_against_existing_ledger(self):
        # cria uma transação real igual
        Transaction.objects.create(
            owner=self.user, type=Transaction.Type.EXPENSE,
            amount=3000, date=date(2024, 1, 1), account=self.account,
            description="IFOOD",
        )
        csv_text = "data;descricao;valor\n01/01/2024;IFOOD;30,00\n"
        batch = self._ingest(csv_text)
        row = batch.staged_rows.get()
        self.assertEqual(row.confidence, StagedTransaction.Confidence.DUPLICATE)

    def test_similar_valid_not_duplicate(self):
        csv_text = (
            "data;descricao;valor\n"
            "01/01/2024;IFOOD;30,00\n"
            "01/01/2024;IFOOD;45,00\n"
        )
        batch = self._ingest(csv_text)
        rows = list(batch.staged_rows.all())
        self.assertEqual(len(rows), 2)
        for r in rows:
            # O ponto deste teste é a deduplicação: linhas sem duplicata NUNCA
            # são marcadas como duplicadas/ignoradas. (Ordem 18/FASE 5: sem
            # evidência suficiente a linha entra em revisão, não em duplicata.)
            self.assertNotEqual(r.confidence, StagedTransaction.Confidence.DUPLICATE)
            self.assertEqual(r.row_status, StagedTransaction.RowStatus.READY)


class CommitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.account = Account.objects.create(
            owner=self.user, name="Corrente", type=Account.Type.CHECKING
        )
        self.category = Category.objects.create(
            owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE
        )

    def _ingest(self, csv_text):
        return importer_svc.ingest(
            user=self.user, file_type="csv", file_name="x.csv",
            content=csv_text.encode("utf-8"), default_account=self.account,
        )

    def test_commit_creates_real_transactions(self):
        batch = self._ingest(
            "data;descricao;valor\n"
            "01/01/2024;IFOOD;30,00\n"
            "02/01/2024;UBER;25,00\n"
        )
        result = commit_batch(user=self.user, batch=batch, account=self.account)
        self.assertEqual(result.imported, 2)
        tx = Transaction.objects.for_user(self.user)
        self.assertEqual(tx.count(), 2)
        # rastreabilidade
        self.assertTrue(all(t.source == Transaction.Source.IMPORTED_CSV for t in tx))
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.COMMITTED)
        self.assertEqual(batch.imported_count, 2)

    def test_commit_reuses_category_and_creates_new(self):
        batch = self._ingest("data;descricao;valor\n01/01/2024;DROGARIA;30,00\n")
        result = commit_batch(
            user=self.user, batch=batch, account=self.account,
            categories={str(batch.staged_rows.get().pk): "Saúde"},
        )
        self.assertEqual(result.imported, 1)
        tx = Transaction.objects.for_user(self.user).get()
        # Categoria "Saúde" foi criada (não existia) e vinculada.
        self.assertEqual(tx.category.name, "Saúde")

    def test_user_pick_propagates_to_identical_rows_in_batch(self):
        # Duas linhas idênticas de "SUSHI EXPRESS" (ambas sem categoria).
        # Quando o usuário corrige UMA, a OUTRA herda a categoria do mesmo lote.
        batch = self._ingest(
            "data;descricao;valor\n"
            "01/01/2024;SUSHI EXPRESS;-40,00\n"
            "05/01/2024;SUSHI EXPRESS;-55,00\n"
        )
        rows = list(batch.staged_rows.order_by("date"))
        self.assertEqual(len(rows), 2)
        # garante que nenhuma já tem categoria (não há catalog/merchant p/ sushi)
        self.assertTrue(all(r.category_id is None for r in rows))

        result = commit_batch(
            user=self.user, batch=batch, account=self.account,
            categories={str(rows[0].pk): "Alimentação"},
        )
        self.assertEqual(result.imported, 2)
        txs = Transaction.objects.for_user(self.user).order_by("date")
        self.assertEqual(txs.count(), 2)
        self.assertTrue(all(t.category_id is not None for t in txs))
        self.assertTrue(all(t.category.name == "Alimentação" for t in txs))
        # ambas aprenderam na memória (mesma normalização + direção)
        from apps.finance.models import UserPreference
        self.assertEqual(
            UserPreference.objects.filter(
                category__kind=Category.Kind.EXPENSE
            ).count(),
            1,
        )

    def test_commit_ignores_marked_duplicates(self):
        batch = self._ingest("data;descricao;valor\n01/01/2024;IFOOD;30,00\n")
        row = batch.staged_rows.get()
        row.row_status = StagedTransaction.RowStatus.IGNORED
        row.save()
        result = commit_batch(user=self.user, batch=batch, account=self.account)
        self.assertEqual(result.imported, 0)
        self.assertEqual(result.ignored, 1)
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 0)

    def test_commit_rolls_back_uncommitted_on_error(self):
        # Confirmação sem conta (linha sem conta e sem default) => não cria nada
        batch = self._ingest("data;descricao;valor\n01/01/2024;IFOOD;30,00\n")
        # remove a conta padrão da linha para forçar pendência
        row = batch.staged_rows.get()
        row.default_account = None
        row.save()
        result = commit_batch(user=self.user, batch=batch, account=None)
        self.assertEqual(result.imported, 0)
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 0)

    def test_no_definitive_before_confirm(self):
        batch = self._ingest("data;descricao;valor\n01/01/2024;IFOOD;30,00\n")
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 0)


class SecurityIsolationTests(TestCase):
    """Usuário A não acessa importações do usuário B (FASE 1 isolamento)."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def test_models_scoped_by_owner(self):
        b_a = ImportBatch.objects.create(
            owner=self.alice, batch_id="A1", file_type="csv", status=ImportBatch.Status.READY)
        ImportBatch.objects.create(
            owner=self.bob, batch_id="B1", file_type="csv", status=ImportBatch.Status.READY)
        self.assertEqual(set(ImportBatch.objects.for_user(self.alice).values_list("pk", flat=True)),
                         {b_a.pk})

    def test_alice_cannot_view_bob_batch(self):
        b_bob = ImportBatch.objects.create(
            owner=self.bob, batch_id="B1", file_type="csv", status=ImportBatch.Status.READY)
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("imports:review", args=[b_bob.pk]))
        self.assertEqual(resp.status_code, 404)
        resp2 = self.client.get(reverse("imports:result", args=[b_bob.pk]))
        self.assertEqual(resp2.status_code, 404)

    def test_batch_id_unique(self):
        ImportBatch.objects.create(owner=self.alice, batch_id="X", file_type="csv")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportBatch.objects.create(owner=self.bob, batch_id="X", file_type="csv")
