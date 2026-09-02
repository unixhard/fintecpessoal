"""Testes da camada de serviços da app cards.

Cobrem: compra à vista e parcelada, parcelamento (2x/3x/12x/arredondamento),
determinação de fatura (datas limítrofes, virada de mês/ano, não duplicação),
pagamento de fatura (liquidação sem dupla contabilização), leituras do cartão
e isolamento multiusuário no nível de serviço.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.models import Account, Transaction
from apps.finance.services.balances import account_balance
from apps.finance.services.errors import (
    ForbiddenResourceError,
    InvalidAmountError,
    InvalidStateError,
)

from .models import CreditCard, CreditCardInvoice, Installment, InstallmentPurchase
from .services.invoices import (
    determine_invoice,
    get_or_create_invoice,
    pay_invoice,
    roll_invoice_statuses,
)
from .services.purchases import create_card_purchase
from .services.reads import card_usage

User = get_user_model()


class BaseCardServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")
        self.bank = Account.objects.create(
            owner=self.user, name="Banco", initial_balance=1000000
        )
        self.card = CreditCard.objects.create(
            owner=self.user, name="Cartão", limit=500000,
            payment_account=self.bank, closing_day=10, due_day=5,
        )


class CreateCardPurchaseTests(BaseCardServiceTestCase):
    def test_at_vista_purchase_single_installment_no_immediate_debit(self):
        purchase = create_card_purchase(
            user=self.user, card=self.card, description="Sapato",
            total_amount=60000, installment_count=1,
            first_due_date=date(2026, 2, 5),
        )
        self.assertEqual(purchase.installment_count, 1)
        self.assertEqual(purchase.installments.count(), 1)
        # NÃO debita a conta bancária imediatamente:
        self.assertEqual(Transaction.objects.for_user(self.user).count(), 0)
        self.assertEqual(account_balance(self.bank), 1000000)

    def test_parcelada_12x(self):
        purchase = create_card_purchase(
            user=self.user, card=self.card, description="Notebook",
            total_amount=120000, installment_count=12,
            first_due_date=date(2026, 2, 10),
        )
        insts = list(purchase.installments.order_by("number"))
        self.assertEqual(len(insts), 12)
        self.assertEqual(sum(i.amount for i in insts), 120000)
        self.assertEqual([i.amount for i in insts[:11]], [10000] * 11)
        self.assertEqual(insts[-1].amount, 10000)

    def test_rejects_other_users_card(self):
        other_card = CreditCard.objects.create(owner=self.other, name="Outro")
        with self.assertRaises(ForbiddenResourceError):
            create_card_purchase(
                user=self.user, card=other_card, description="X",
                total_amount=100, installment_count=1,
                first_due_date=date(2026, 2, 5),
            )

    def test_rejects_invalid_amount_or_count(self):
        with self.assertRaises(InvalidAmountError):
            create_card_purchase(
                user=self.user, card=self.card, description="X",
                total_amount=0, installment_count=1,
                first_due_date=date(2026, 2, 5),
            )
        with self.assertRaises(InvalidAmountError):
            create_card_purchase(
                user=self.user, card=self.card, description="X",
                total_amount=100, installment_count=0,
                first_due_date=date(2026, 2, 5),
            )


class InstallmentRoundingTests(BaseCardServiceTestCase):
    def _amounts(self, total, count):
        purchase = create_card_purchase(
            user=self.user, card=self.card, description="R",
            total_amount=total, installment_count=count,
            first_due_date=date(2026, 2, 10),
        )
        return [i.amount for i in purchase.installments.order_by("number")]

    def test_2x(self):
        self.assertEqual(self._amounts(1001, 2), [500, 501])

    def test_3x_rounding_on_last(self):
        self.assertEqual(self._amounts(1000, 3), [333, 333, 334])

    def test_12x_exact_sum(self):
        amounts = self._amounts(120000, 12)
        self.assertEqual(len(amounts), 12)
        self.assertEqual(sum(amounts), 120000)

    def test_exact_divisible(self):
        self.assertEqual(self._amounts(60000, 6), [10000] * 6)


class InvoiceDeterminationTests(BaseCardServiceTestCase):
    def test_purchase_before_closing_same_cycle(self):
        period = determine_invoice(self.card, date(2026, 9, 9))
        # Fecha dia 10 do mesmo mês:
        self.assertEqual(period["closing_date"], date(2026, 9, 10))
        self.assertEqual(period["period_end"], date(2026, 9, 10))
        self.assertEqual(period["period_start"], date(2026, 8, 11))
        self.assertEqual(period["due_date"], date(2026, 10, 5))

    def test_purchase_on_closing_day_stays_in_cycle(self):
        period = determine_invoice(self.card, date(2026, 9, 10))
        self.assertEqual(period["closing_date"], date(2026, 9, 10))

    def test_purchase_after_closing_next_cycle(self):
        period = determine_invoice(self.card, date(2026, 9, 11))
        self.assertEqual(period["closing_date"], date(2026, 10, 10))
        self.assertEqual(period["period_start"], date(2026, 9, 11))
        self.assertEqual(period["due_date"], date(2026, 11, 5))

    def test_year_rollover(self):
        period = determine_invoice(self.card, date(2026, 12, 11))
        self.assertEqual(period["closing_date"], date(2027, 1, 10))
        self.assertEqual(period["period_start"], date(2026, 12, 11))
        self.assertEqual(period["due_date"], date(2027, 2, 5))

    def test_month_rollover(self):
        period = determine_invoice(self.card, date(2026, 11, 11))
        self.assertEqual(period["closing_date"], date(2026, 12, 10))

    def test_get_or_create_is_idempotent(self):
        a = get_or_create_invoice(self.user, self.card, date(2026, 9, 9))
        b = get_or_create_invoice(self.user, self.card, date(2026, 9, 1))
        self.assertEqual(a.id, b.id)
        self.assertEqual(
            CreditCardInvoice.objects.for_user(self.user).count(), 1
        )


class InvoicePaymentTests(BaseCardServiceTestCase):
    def setUp(self):
        super().setUp()
        self.purchase = create_card_purchase(
            user=self.user, card=self.card, description="Compra",
            total_amount=30000, installment_count=3,
            first_due_date=date(2026, 2, 10),
        )
        # Com fechamento dia 10, cada parcela (fev/10, mar/10, abr/10) fecha em
        # um ciclo próprio. A fatura da primeira parcela contém só ela:
        self.invoice = self.purchase.installments.first().invoice
        self.assertEqual(self.purchase.installments.count(), 3)
        self.assertEqual(self.invoice.amount, 10000)
        self.assertEqual(self.invoice.installments.count(), 1)

    def test_full_payment_liquidates_and_withdraws_once(self):
        tx = pay_invoice(
            user=self.user, invoice=self.invoice, account=self.bank,
            date=date(2026, 3, 5),
        )
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.amount, 10000)
        self.assertEqual(tx.account_id, self.bank.id)
        # Saída da conta ocorreu uma vez:
        self.assertEqual(account_balance(self.bank), 1000000 - 10000)
        self.assertEqual(
            Transaction.objects.filter(
                type=Transaction.Type.EXPENSE, account=self.bank
            ).count(),
            1,
        )
        # Fatura liquidada e parcelas pagas:
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CreditCardInvoice.Status.PAID)
        self.assertTrue(all(
            i.status == Installment.Status.PAID for i in self.invoice.installments.all()
        ))

    def test_second_installment_in_own_invoice(self):
        # Cada parcela mensal fecha em seu próprio ciclo (devido a 10/03, 10/04...).
        second = self.purchase.installments.order_by("number")[1]
        self.assertNotEqual(second.invoice_id, self.invoice.id)
        self.assertEqual(second.invoice.amount, 10000)

    def test_invoice_amount_is_sum_of_its_installments(self):
        # Duas compras à vista no mesmo ciclo caem na mesma fatura e somam.
        invoice = get_or_create_invoice(self.user, self.card, date(2026, 9, 5))
        create_card_purchase(
            user=self.user, card=self.card, description="A",
            total_amount=10000, installment_count=1, first_due_date=date(2026, 9, 5),
        )
        create_card_purchase(
            user=self.user, card=self.card, description="B",
            total_amount=20000, installment_count=1, first_due_date=date(2026, 9, 4),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount, 30000)
        self.assertEqual(invoice.installments.count(), 2)

    def test_no_double_counting_of_purchases(self):
        # A compra não vira despesa no banco; só o pagamento gera a saída única.
        self.assertEqual(
            Transaction.objects.filter(
                type=Transaction.Type.EXPENSE, account=self.bank
            ).count(),
            0,
        )
        pay_invoice(
            user=self.user, invoice=self.invoice, account=self.bank,
            date=date(2026, 3, 5),
        )
        self.assertEqual(
            Transaction.objects.filter(
                type=Transaction.Type.EXPENSE, account=self.bank
            ).count(),
            1,
        )

    def test_cannot_pay_other_users_invoice(self):
        with self.assertRaises(ForbiddenResourceError):
            pay_invoice(
                user=self.other, invoice=self.invoice, account=self.bank,
                date=date(2026, 3, 5),
            )

    def test_cannot_pay_with_other_users_account(self):
        other_bank = Account.objects.create(owner=self.other, name="Banco Bob")
        with self.assertRaises(ForbiddenResourceError):
            pay_invoice(
                user=self.user, invoice=self.invoice, account=other_bank,
                date=date(2026, 3, 5),
            )

    def test_cannot_pay_above_due(self):
        with self.assertRaises(InvalidAmountError):
            pay_invoice(
                user=self.user, invoice=self.invoice, account=self.bank,
                amount=999999, date=date(2026, 3, 5),
            )

    def test_only_one_payment_allowed(self):
        pay_invoice(
            user=self.user, invoice=self.invoice, account=self.bank,
            date=date(2026, 3, 5),
        )
        with self.assertRaises(InvalidStateError):
            pay_invoice(
                user=self.user, invoice=self.invoice, account=self.bank,
                date=date(2026, 3, 6),
            )


class CardReadsTests(BaseCardServiceTestCase):
    def test_usage_after_installment_purchase(self):
        create_card_purchase(
            user=self.user, card=self.card, description="3x",
            total_amount=30000, installment_count=3,
            first_due_date=date(2026, 2, 10),
        )
        usage = card_usage(self.card)
        self.assertEqual(usage["limit"], 500000)
        self.assertEqual(usage["used"], 30000)
        self.assertEqual(usage["available"], 500000 - 30000)

    def test_card_summary_rejects_other_users_card(self):
        with self.assertRaises(ForbiddenResourceError):
            from .services.reads import card_summary

            card_summary(self.other, self.card)


class InvoiceCycleAutoTests(BaseCardServiceTestCase):
    """Cenários A–E do ciclo automático de faturas + avanço de status.

    Validam a atribuição determinística de cada compra/parcela ao ciclo correto
    (A/B/C), a idempotência da geração (D), a liquidação única (E) e o
    rollover OPEN->CLOSED / ->OVERDUE (agora com a rotina idempotente).
    """

    # closing_day=10, due_day=5 já configurados no BaseCardServiceTestCase.

    def _make_invoice(self, closing_date, due_date, status="open"):
        return CreditCardInvoice.objects.create(
            owner=self.user,
            card=self.card,
            period_start=date(2026, 1, 1),
            period_end=closing_date,
            closing_date=closing_date,
            due_date=due_date,
            status=status,
        )

    # --- Cenário A: compra antes do fechamento fica no ciclo atual ---
    def test_a_purchase_before_closing_goes_to_current_cycle(self):
        inv = get_or_create_invoice(self.user, self.card, date(2026, 9, 9))
        self.assertEqual(inv.closing_date, date(2026, 9, 10))
        self.assertEqual(inv.status, CreditCardInvoice.Status.OPEN)

    # --- Cenário B: compra após o fechamento vai para o próximo ciclo ---
    def test_b_purchase_after_closing_goes_to_next_cycle(self):
        inv = get_or_create_invoice(self.user, self.card, date(2026, 9, 11))
        self.assertEqual(inv.closing_date, date(2026, 10, 10))
        self.assertNotEqual(
            inv.closing_date,
            get_or_create_invoice(self.user, self.card, date(2026, 9, 9)).closing_date,
        )

    # --- Cenário C: parcelas distribuem em ciclos distintos ---
    def test_c_each_installment_assigned_to_its_own_cycle(self):
        purchase = create_card_purchase(
            user=self.user, card=self.card, description="Ciclos",
            total_amount=30000, installment_count=3,
            first_due_date=date(2026, 2, 10),
        )
        invoices = {
            i.invoice_id for i in purchase.installments.all()
        }
        self.assertEqual(
            len(invoices), 3,
            "Cada parcela mensal deve pertencer a uma fatura de ciclo própria.",
        )

    # --- Cenário D: geração idempotente (não duplica) ---
    def test_d_generation_is_idempotent(self):
        a = get_or_create_invoice(self.user, self.card, date(2026, 9, 9))
        b = get_or_create_invoice(self.user, self.card, date(2026, 9, 1))
        self.assertEqual(a.id, b.id)
        self.assertEqual(
            CreditCardInvoice.objects.for_user(self.user).count(), 1
        )
        r1 = roll_invoice_statuses(today=date(2026, 8, 1))
        r2 = roll_invoice_statuses(today=date(2026, 8, 1))
        self.assertEqual(r1, r2)

    # --- Cenário E: pagamento liquida uma única vez (já coberto; reafirmar) ---
    def test_e_payment_sets_paid_and_stays_paid_after_rollover(self):
        purchase = create_card_purchase(
            user=self.user, card=self.card, description="E",
            total_amount=10000, installment_count=1, first_due_date=date(2026, 9, 9),
        )
        inv = purchase.installments.first().invoice
        pay_invoice(
            user=self.user, invoice=inv, account=self.bank,
            date=date(2026, 10, 1),
        )
        # Mesmo vencendo, fatura paga nunca vira atrasada:
        result = roll_invoice_statuses(today=date(2026, 11, 1))
        inv.refresh_from_db()
        self.assertEqual(result["overdue"], 0)
        self.assertEqual(inv.status, CreditCardInvoice.Status.PAID)

    # --- Rollover OPEN -> CLOSED após o fechamento ---
    def test_rollover_open_to_closed_after_closing_date(self):
        inv = self._make_invoice(date(2026, 9, 10), date(2026, 10, 5))
        result = roll_invoice_statuses(today=date(2026, 9, 11))
        self.assertEqual(result, {"closed": 1, "overdue": 0})
        inv.refresh_from_db()
        self.assertEqual(inv.status, CreditCardInvoice.Status.CLOSED)

    # --- Rollover OPEN/CLOSED -> OVERDUE após o vencimento ---
    def test_rollover_to_overdue_after_due_date(self):
        open_inv = self._make_invoice(date(2026, 9, 10), date(2026, 10, 5))
        closed_inv = self._make_invoice(date(2026, 8, 10), date(2026, 9, 5))
        closed_inv.status = CreditCardInvoice.Status.CLOSED
        closed_inv.save()
        result = roll_invoice_statuses(today=date(2026, 11, 1))
        self.assertEqual(result["overdue"], 2)
        open_inv.refresh_from_db()
        closed_inv.refresh_from_db()
        self.assertEqual(open_inv.status, CreditCardInvoice.Status.OVERDUE)
        self.assertEqual(closed_inv.status, CreditCardInvoice.Status.OVERDUE)

    # --- Fatura futura permanece OPEN ---
    def test_rollover_keeps_future_invoice_open(self):
        inv = self._make_invoice(date(2026, 9, 10), date(2026, 10, 5))
        result = roll_invoice_statuses(today=date(2026, 9, 9))
        self.assertEqual(result, {"closed": 0, "overdue": 0})
        inv.refresh_from_db()
        self.assertEqual(inv.status, CreditCardInvoice.Status.OPEN)

    # --- Idempotência: não altera nada já avançado na mesma data ---
    def test_rollover_is_idempotent_across_runs(self):
        inv = self._make_invoice(date(2026, 9, 10), date(2026, 10, 5))
        r1 = roll_invoice_statuses(today=date(2026, 10, 6))
        r2 = roll_invoice_statuses(today=date(2026, 10, 6))
        self.assertEqual(r1, {"closed": 0, "overdue": 1})
        self.assertEqual(r2, {"closed": 0, "overdue": 0})
        inv.refresh_from_db()
        self.assertEqual(inv.status, CreditCardInvoice.Status.OVERDUE)
