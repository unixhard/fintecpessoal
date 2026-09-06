"""Semeia uma conta de demonstração completa para teste local/área de produção.

Cria (idempotente) um usuário ``demo`` com dados realistas em TODAS as áreas do
produto para que os gráficos do dashboard (evolução mensal, donut por categoria,
fluxo, metas, orçamentos, dívidas, cartão/faturas, recorrências) tenham conteúdo:

- usuário + perfil com onboarding completo;
- taxonomia padrão de categorias;
- contas (corrente + poupança) e cartão de crédito;
- transações de receita (salário) e despesa variadas nos últimos 6 meses,
  distribuídas por categoria e com merchants do catálogo quando conhecidos;
- compras no cartão (à vista + parcelada em 12x) e pagamento de fatura antiga;
- meta (reserva de emergência), orçamento global e por categoria;
- dívida ativa e regras de recorrência.

Idempotente: re-executar nunca duplica lançamentos. ``--reset`` apaga o usuário
demo e recria tudo do zero.
"""

import os
import secrets

from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.finance.models import Account, Transaction
from apps.finance.services.categories import seed_default_categories
from apps.cards.models import CreditCard, CreditCardInvoice
from apps.cards.models import add_months

DEMO_USERNAME_DEFAULT = "demo"
DEMO_EMAIL_DEFAULT = "demo@fintec.app"


def _clamp_day(year, month, day):
    from calendar import monthrange
    return min(day, monthrange(year, month)[1])


def _days_in_month(year, month):
    from calendar import monthrange
    return monthrange(year, month)[1]


def _shift_months(d, months):
    return add_months(d, months)


class Command(BaseCommand):
    help = "Semeia um usuário demo com dados completos em todos os domínios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.environ.get("DEMO_USERNAME") or DEMO_USERNAME_DEFAULT,
            help="Nome de usuário demo (env DEMO_USERNAME).",
        )
        parser.add_argument(
            "--email",
            default=os.environ.get("DEMO_EMAIL") or DEMO_EMAIL_DEFAULT,
            help="E-mail do usuário demo.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Apaga o usuário demo e recria tudo do zero.",
        )

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD")
        if not password:
            password = secrets.token_urlsafe(9)
            self.stdout.write(
                self.style.WARNING(
                    "DEMO_PASSWORD não definida — gerada uma senha aleatória. "
                    "Defina DEMO_PASSWORD no Render/ambiente para uma senha conhecida."
                )
            )

        User = get_user_model()
        username = options["username"]

        if options["reset"]:
            existing = User.objects.filter(username=username).first()
            if existing is not None:
                self._delete_demo_user(existing)

        user = User.objects.filter(username=username).first()

        if user is None:
            user = User.objects.create_user(
                username=username,
                email=options["email"],
                password=password,
                first_name="Usuário",
                last_name="Demonstração",
            )
            self.stdout.write(self.style.SUCCESS(f"Criado usuário demo '{username}'."))
        else:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(
                self.style.SUCCESS(f"Usuário demo '{username}' já existia — senha atualizada.")
            )

        self._ensure_profile(user)
        seed_default_categories(user=user)

        if self._already_seeded(user):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dados demo já presentes para '{username}' (reinício idempotente). "
                    f"Senha: {password}"
                )
            )
            return

        with transaction.atomic():
            self._seed(user)

        self.stdout.write(self.style.SUCCESS("=-" * 20))
        self.stdout.write(self.style.SUCCESS(f"DEMO PRONTO — usuário: {username} / senha: {password}"))
        self.stdout.write(self.style.SUCCESS("=-" * 20))

    def _ensure_profile(self, user):
        profile = user.profile
        profile.onboarding_completed = True
        profile.display_name = "Conta Demo"
        profile.save(update_fields=["onboarding_completed", "display_name"])

    def _delete_demo_user(self, user):
        """Apaga tudo do usuário demo na ordem correta (respeita PROTECT)."""
        from apps.cards.models import CreditCard, CreditCardInvoice, Installment, InstallmentPurchase
        from apps.goals.models import Goal
        from apps.budgets.models import Budget
        from apps.debts.models import Debt
        from apps.finance.models import (
            Account, Category, ClassificationRule, Merchant, MerchantAlias,
            RecurringRule, Transaction, Transfer, TransactionAnalysis, UserPreference,
        )

        for model in (
            TransactionAnalysis,
            UserPreference,
            Installment,
            InstallmentPurchase,
            CreditCardInvoice,
            CreditCard,
            Transfer,
            RecurringRule,
        ):
            model.objects.filter(owner=user).delete()
        # Transações dependem de Account (PROTECT). Payment de fatura/dívida
        # gera Transaction vinculada; apagar antes das contas.
        Transaction.objects.filter(owner=user).delete()
        Debt.objects.filter(owner=user).delete()
        Budget.objects.filter(owner=user).delete()
        Goal.objects.filter(owner=user).delete()
        ClassificationRule.objects.filter(owner=user).delete()
        Account.objects.filter(owner=user).delete()
        Category.objects.filter(owner=user).delete()
        # Merchants pessoais (globais, owner=None, não pertencem ao demo).
        MerchantAlias.objects.filter(owner=user).delete()
        Merchant.objects.filter(owner=user).delete()
        user.delete()

    def _already_seeded(self, user):
        return Transaction.objects.for_user(user).exists()

    def _seed(self, user):
        from apps.finance.services.accounts import create_account
        from apps.finance.services.transactions import record_income, record_expense
        from apps.finance.services.transfers import transfer_between
        from apps.cards.services.purchases import create_card_purchase
        from apps.cards.services.invoices import pay_invoice
        from apps.goals.services.goals import create_goal, add_goal_contribution
        from apps.budgets.services.budgets import create_budget
        from apps.debts.services.debts import create_debt, record_debt_payment
        from apps.finance.services.recurrences import create_rule

        today = timezone.localdate()

        checking = create_account(
            user=user,
            name="Conta Corrente",
            type=Account.Type.CHECKING,
            initial_balance=250_000,
            institution="Banco Inter",
            initial_balance_date=today,
        )
        savings = create_account(
            user=user,
            name="Poupança",
            type=Account.Type.SAVINGS,
            initial_balance=80_000,
            institution="Nubank",
            initial_balance_date=today,
        )

        card = CreditCard.objects.create(
            owner=user,
            name="Cartão Nubank",
            institution="Nubank",
            limit=3_000_000,
            closing_day=10,
            due_day=20,
            payment_account=checking,
        )

        # Categorias da taxonomia padrão (por nome).
        def cat(name):
            from apps.finance.models import Category
            return Category.objects.filter(owner=user, name=name).first()

        def merchant(name):
            from apps.finance.models import Merchant
            return Merchant.objects.filter(owner__isnull=True, name=name).first()

        # ---- Histórico de 6 meses: salário + despesas variadas ----
        salary = cat("Salário")
        aluguel = cat("Aluguel")
        supermercado = cat("Supermercado")
        energia = cat("Energia elétrica")
        transporte = cat("Aplicativos")
        restaurante = cat("Restaurante")
        delivery = cat("Delivery")
        streaming_video = cat("Streaming de vídeo")
        celular = cat("Celular")
        internet = cat("Internet")
        academia = cat("Academia")
        farmacia = cat("Farmácia")
        vestuario = cat("Vestuário")

        months = 6
        for offset in range(months - 1, -1, -1):
            month_start = _shift_months(today.replace(day=1), -offset)
            y, m = month_start.year, month_start.month
            dim = _days_in_month(y, m)

            salary_day = _clamp_day(y, m, 5)
            if salary_day <= today.day or offset > 0:
                record_income(
                    user=user, account=checking, amount=3_700_00,
                    date=date(y, m, salary_day), description="Salário — TechCorp Ltda",
                    category=salary, merchant=merchant("LinkedIn"),
                )

            rent_day = _clamp_day(y, m, 10)
            if rent_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=160_000,
                    date=date(y, m, rent_day), description="Aluguel — Apartamento 301",
                    category=aluguel, merchant=merchant("Aluguel"),
                )

            market_day = _clamp_day(y, m, 7)
            if market_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=45_000,
                    date=date(y, m, market_day), description="Pão de Açúcar — mercado semanal",
                    category=supermercado, merchant=merchant("Pão de Açúcar"),
                )

            energy_day = _clamp_day(y, m, 15)
            if energy_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=18_000,
                    date=date(y, m, energy_day), description="Enel — energia elétrica",
                    category=energia, merchant=merchant("Enel"),
                )

            uber_day = _clamp_day(y, m, 12)
            if uber_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=2_400,
                    date=date(y, m, uber_day), description="Uber — corrida ao trabalho",
                    category=transporte, merchant=merchant("Uber"),
                )

            food_day = _clamp_day(y, m, 18)
            if food_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=9_000,
                    date=date(y, m, food_day), description="Restaurante na sexta-feira",
                    category=restaurante, merchant=merchant("Restaurante"),
                )

            delivery_day = _clamp_day(y, m, 21)
            if delivery_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=6_000,
                    date=date(y, m, delivery_day), description="iFood — pedido do jantar",
                    category=delivery, merchant=merchant("iFood"),
                )

            stream_day = _clamp_day(y, m, 20)
            if stream_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=5_500,
                    date=date(y, m, stream_day), description="Netflix — assinatura mensal",
                    category=streaming_video, merchant=merchant("Netflix"),
                )

            phone_day = _clamp_day(y, m, 22)
            if phone_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=4_000,
                    date=date(y, m, phone_day), description="Vivo — plano celular",
                    category=celular, merchant=merchant("Vivo"),
                )

            net_day = _clamp_day(y, m, 24)
            if net_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=9_900,
                    date=date(y, m, net_day), description="Internet fibra — provedor local",
                    category=internet, merchant=merchant("Internet"),
                )

            gym_day = _clamp_day(y, m, 25)
            if gym_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=12_000,
                    date=date(y, m, gym_day), description="Academia — mensalidade",
                    category=academia, merchant=merchant("Academia"),
                )

            pharmacy_day = _clamp_day(y, m, 17)
            if pharmacy_day <= today.day or offset > 0:
                record_expense(
                    user=user, account=checking, amount=3_500,
                    date=date(y, m, pharmacy_day), description="Droga Raia — farmácia",
                    category=farmacia, merchant=merchant("Farmácia"),
                )

            if m % 2 == 0 and offset > 0:
                clothes_day = _clamp_day(y, m, 26)
                record_expense(
                    user=user, account=checking, amount=14_900,
                    date=date(y, m, clothes_day), description="C&A — vestuário",
                    category=vestuario, merchant=merchant("C&A"),
                )

            # Transferência mensal para a poupança.
            save_day = _clamp_day(y, m, 9)
            if (save_day <= today.day or offset > 0) and offset < 3:
                transfer_between(
                    user=user, from_account=checking, to_account=savings,
                    amount=30_000, date=date(y, m, save_day), notes="Aporte poupança",
                )

        # ---- Cartão: compra à vista + compra parcelada em 12x ----
        create_card_purchase(
            user=user, card=card, description="Restaurante à vista",
            total_amount=9_000, installment_count=1,
            first_due_date=_shift_months(today, -1),
        )
        create_card_purchase(
            user=user, card=card, description="Notebook em 12x",
            total_amount=960_000, installment_count=12,
            first_due_date=_shift_months(today.replace(day=20), -2),
        )

        # Pagamento de uma fatura antiga (gera despesa na conta corrente).
        old_invoice = (
            CreditCardInvoice.objects.filter(owner=user, card=card)
            .filter(status=CreditCardInvoice.Status.OPEN)
            .order_by("due_date")
            .first()
        )
        if old_invoice is not None and old_invoice.amount > 0:
            pay_invoice(
                user=user, invoice=old_invoice, account=checking,
                date=_shift_months(old_invoice.due_date, 0),
                notes="Pagamento fatura demo",
            )

        # ---- Metas ----
        reserve = create_goal(
            user=user, name="Reserva de emergência",
            target_amount=900_000, current_amount=0,
            priority="high", target_date=_shift_months(today, 12),
            notes="3 salários de reserva.",
        )
        for offset in range(6):
            add_goal_contribution(
                user=user, goal=reserve, amount=10_000,
                ref_date=_shift_months(today, -offset),
            )

        # ---- Orçamentos ----
        create_budget(user=user, kind="global", limit_amount=700_000)
        create_budget(
            user=user, kind="category", limit_amount=260_000,
            category=supermercado,
        )

        # ---- Dívidas + pagamentos ----
        debt = create_debt(
            user=user, name="Financiamento do carro",
            total_amount=4_200_000, paid_amount=0,
            interest_rate=1.2, creditor="Banco Inter",
            start_date=_shift_months(today, -8), end_date=_shift_months(today, 40),
        )
        for k in range(3):
            payment_date = _shift_months(today, -(3 - k))
            record_debt_payment(
                user=user, debt=debt, account=checking, amount=70_000,
                date=payment_date, notes="Parcela financiamento",
            )

        # ---- Recorrências ----
        create_rule(
            user=user, kind="income", title="Salário TechCorp",
            amount=3_700_00, frequency="monthly", start_date=_shift_months(today, -6),
            account=checking, category=salary, day_of_month=5,
        )
        create_rule(
            user=user, kind="expense", title="Aluguel",
            amount=160_000, frequency="monthly", start_date=_shift_months(today, -6),
            account=checking, category=aluguel, day_of_month=10,
        )

        # Conta padrão no perfil.
        from apps.finance.models import Account as _Account
        profile = user.profile
        profile.default_account = _Account.objects.filter(owner=user, name="Conta Corrente").first()
        profile.save(update_fields=["default_account"])