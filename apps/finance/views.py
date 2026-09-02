"""Views financeiras (contas, categorias, lançamentos, transferências,
recorrências).

Convenção do projeto: views coordenam `request -> form -> service ->
redirect/render`. Nenhuma regra financeira vive aqui — valores e regras são
tratados pelos serviços (regra 16). Toda consulta usada é isolada por usuário
(via ``for_user``) e toda escrita passa pelos serviços, que validam ownership.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin

from apps.finance.services import (
    accounts as accounts_svc,
    balances as balances_svc,
    categories as categories_svc,
    recurrences as recurrences_svc,
    transactions as transactions_svc,
    transfers as transfers_svc,
)

from .forms import (
    AccountCreateForm,
    AccountEditForm,
    CategoryForm,
    ExpenseForm,
    IncomeForm,
    RecurringForm,
    TransactionEditForm,
    TransferForm,
)
from .models import Account, Category, RecurringRule, Transaction


def _fmt_brl(cents):
    """Formata centavos (int) como 'R$ 1.234,56' — espelha o filtro `centavos`."""
    if cents is None:
        return "-"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    reais, cents_part = divmod(cents, 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cents_part:02d}"


# --------------------------------------------------------------------------- #
# Contas
# --------------------------------------------------------------------------- #


class AccountListView(LoginRequiredMixin, ListView):
    model = Account
    template_name = "finance/account_list.html"
    context_object_name = "accounts"

    def get_queryset(self):
        return (
            Account.objects.for_user(self.request.user)
            .order_by("-status", "name")
            .select_related()
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        accounts = list(self.get_queryset())
        for account in accounts:
            account.balance = balances_svc.account_balance(account)
        ctx["accounts"] = accounts
        ctx["active_accounts"] = [
            a for a in accounts if a.status == Account.Status.ACTIVE
        ]
        ctx["archived_accounts"] = [
            a for a in accounts if a.status != Account.Status.ACTIVE
        ]
        return ctx


class _OwnedObjectMixin(SingleObjectMixin):
    model = None
    permission_denied_message = "Recurso não encontrado."

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            self.model.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        self.object = obj
        return obj


class AccountCreateView(LoginRequiredMixin, FormView):
    template_name = "finance/account_form.html"
    form_class = AccountCreateForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova conta"
        return ctx

    def form_valid(self, form):
        user = self.request.user
        accounts_svc.create_account(
            user=user,
            name=form.cleaned_data["name"],
            type=form.cleaned_data["type"],
            institution=form.cleaned_data.get("institution") or "",
            initial_balance=form.cleaned_data.get("initial_balance") or 0,
        )
        messages.success(self.request, "Conta criada com sucesso.")
        return redirect(reverse("finance:account_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class AccountDetailView(LoginRequiredMixin, _OwnedObjectMixin, TemplateView):
    model = Account
    template_name = "finance/account_detail.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        account = self.get_object()
        account.balance = balances_svc.account_balance(account)
        ctx = super().get_context_data(**kwargs)
        ctx["account"] = account
        transactions = (
            Transaction.objects.for_user(user)
            .filter(account=account)
            .order_by("-date", "-id")
        )
        ctx["recent_transactions"] = transactions[:10]
        ctx["transaction_count"] = transactions.count()
        return ctx


class AccountEditView(LoginRequiredMixin, _OwnedObjectMixin, FormView):
    model = Account
    template_name = "finance/account_form.html"
    form_class = AccountEditForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar conta"
        return ctx

    def get_initial(self):
        account = self.get_object()
        return {
            "name": account.name,
            "type": account.type,
            "institution": account.institution,
        }

    def form_valid(self, form):
        account = self.get_object()
        accounts_svc.update_account(
            user=self.request.user,
            account=account,
            name=form.cleaned_data["name"],
            type=form.cleaned_data["type"],
            institution=form.cleaned_data.get("institution") or "",
        )
        messages.success(self.request, "Conta atualizada.")
        return redirect(reverse("finance:account_detail", args=[account.pk]))


class AccountStatusView(LoginRequiredMixin, View):
    """Arquiva ou reativa uma conta (via os serviços)."""

    action = None  # 'archive' | 'reactivate'

    def post(self, request, *args, **kwargs):
        account = get_object_or_404(
            Account.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        if self.action == "archive":
            accounts_svc.archive_account(user=request.user, account=account)
            messages.success(request, "Conta arquivada.")
        else:
            accounts_svc.reactivate_account(user=request.user, account=account)
            messages.success(request, "Conta reativada.")
        return redirect(reverse("finance:account_list"))


# --------------------------------------------------------------------------- #
# Categorias
# --------------------------------------------------------------------------- #


class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = "finance/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return Category.objects.for_user(self.request.user).order_by(
            "kind", "-status", "name"
        )


class CategoryCreateView(LoginRequiredMixin, FormView):
    template_name = "finance/category_form.html"
    form_class = CategoryForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova categoria"
        return ctx

    def get_initial(self):
        initial = super().get_initial()
        kind = self.request.GET.get("kind") or self.request.POST.get("kind")
        if kind in (Category.Kind.EXPENSE, Category.Kind.INCOME):
            initial["kind"] = kind
        return initial

    def form_valid(self, form):
        categories_svc.create_category(
            user=self.request.user,
            name=form.cleaned_data["name"],
            kind=form.cleaned_data["kind"],
            parent=form.cleaned_data.get("parent"),
        )
        messages.success(self.request, "Categoria criada.")
        # Permite voltar ao formulário de origem (ex.: lançamento em andamento).
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url:
            return redirect(next_url)
        return redirect(reverse("finance:category_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class CategoryEditView(LoginRequiredMixin, _OwnedObjectMixin, FormView):
    model = Category
    template_name = "finance/category_form.html"
    form_class = CategoryForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar categoria"
        return ctx

    def get_initial(self):
        category = self.get_object()
        return {
            "name": category.name,
            "kind": category.kind,
            "parent": category.parent,
        }

    def form_valid(self, form):
        category = self.get_object()
        if category.is_default:
            categories_svc.create_category(
                user=self.request.user,
                name=form.cleaned_data["name"],
                kind=form.cleaned_data["kind"],
                parent=form.cleaned_data.get("parent"),
            )
            messages.info(self.request, "Categoria padrão preservada; uma nova foi criada.")
            return redirect(reverse("finance:category_list"))
        categories_svc.update_category(
            user=self.request.user,
            category=category,
            name=form.cleaned_data["name"],
            kind=form.cleaned_data["kind"],
            parent=form.cleaned_data.get("parent"),
        )
        messages.success(self.request, "Categoria atualizada.")
        return redirect(reverse("finance:category_list"))


class CategoryArchiveView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        category = get_object_or_404(
            Category.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        categories_svc.archive_category(user=request.user, category=category)
        messages.success(request, "Categoria arquivada.")
        return redirect(reverse("finance:category_list"))


# --------------------------------------------------------------------------- #
# Lançamentos (movimentações)
# --------------------------------------------------------------------------- #

TRANSACTION_FILTER_CHOICES = [
    ("all", "Todos"),
    ("income", "Receitas"),
    ("expense", "Despesas"),
    ("transfer", "Transferências"),
    ("adjustment", "Ajustes"),
]


class TransactionListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "finance/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = Transaction.objects.for_user(user).select_related(
            "account", "category", "transfer"
        )
        ttype = self.request.GET.get("type", "all")
        account_id = self.request.GET.get("account")
        category_id = self.request.GET.get("category")
        date_from = self.request.GET.get("from")
        date_to = self.request.GET.get("to")
        q = self.request.GET.get("q", "").strip()

        if ttype != "all":
            mapping = {
                "income": Transaction.Type.INCOME,
                "expense": Transaction.Type.EXPENSE,
                "transfer": Transaction.Type.TRANSFER,
                "adjustment": Transaction.Type.ADJUSTMENT,
            }
            if ttype in mapping:
                qs = qs.filter(type=mapping[ttype])
        if account_id:
            account = get_object_or_404(
                Account.objects.for_user(user), pk=account_id
            )
            qs = qs.filter(account=account)
        if category_id:
            category = get_object_or_404(
                Category.objects.for_user(user), pk=category_id
            )
            qs = qs.filter(category=category)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if q:
            qs = qs.filter(
                Q(description__icontains=q)
                | Q(notes__icontains=q)
                | Q(account__name__icontains=q)
            )

        sort = self.request.GET.get("sort", "-date")
        allowed = {
            "-date": "-date",
            "date": "date",
            "-amount": "-amount",
            "amount": "amount",
            "description": "description",
            "-description": "-description",
        }
        qs = qs.order_by(allowed.get(sort, "-date"), "-id")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        params = self.request.GET
        query = params.urlencode()
        ctx.update(
            {
                "accounts": Account.objects.for_user(user).filter(
                    status=Account.Status.ACTIVE
                ),
                "categories": Category.objects.for_user(user).filter(
                    status=Category.Status.ACTIVE
                ),
                "filter_choices": TRANSACTION_FILTER_CHOICES,
                "current_type": params.get("type", "all"),
                "current_account": params.get("account", ""),
                "current_category": params.get("category", ""),
                "current_from": params.get("from", ""),
                "current_to": params.get("to", ""),
                "current_q": params.get("q", ""),
                "current_sort": params.get("sort", "-date"),
                "query": query,
            }
        )
        return ctx


class TransactionDetailView(LoginRequiredMixin, _OwnedObjectMixin, TemplateView):
    model = Transaction
    template_name = "finance/transaction_detail.html"

    def get_context_data(self, **kwargs):
        transaction = self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["transaction"] = transaction
        editable = not (
            transaction.transfer_id
            or transaction.card_purchase_id
            or (
                hasattr(transaction, "paid_invoices")
                and transaction.paid_invoices.exists()
            )
        )
        ctx["transaction_editable"] = editable
        return ctx


class _TransactionBaseFormView(LoginRequiredMixin, FormView):
    form_class = None
    kind = None
    title = ""
    template_name = "finance/transaction_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["kind"] = self.kind
        return ctx

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class IncomeCreateView(_TransactionBaseFormView):
    form_class = IncomeForm
    kind = Transaction.Type.INCOME
    title = "Nova receita"

    def form_valid(self, form):
        transactions_svc.record_income(
            user=self.request.user,
            account=form.cleaned_data["account"],
            amount=form.cleaned_data["amount"],
            date=form.cleaned_data["date"],
            description=form.cleaned_data.get("description") or "",
            category=form.cleaned_data.get("category"),
            notes=form.cleaned_data.get("notes") or "",
        )
        messages.success(self.request, "Receita registrada.")
        return redirect(reverse("finance:transaction_list"))


class ExpenseCreateView(_TransactionBaseFormView):
    form_class = ExpenseForm
    kind = Transaction.Type.EXPENSE
    title = "Nova despesa"

    def form_valid(self, form):
        transactions_svc.record_expense(
            user=self.request.user,
            account=form.cleaned_data["account"],
            amount=form.cleaned_data["amount"],
            date=form.cleaned_data["date"],
            description=form.cleaned_data.get("description") or "",
            category=form.cleaned_data.get("category"),
            notes=form.cleaned_data.get("notes") or "",
        )
        messages.success(self.request, "Despesa registrada.")
        return redirect(reverse("finance:transaction_list"))


class TransactionCreateView(LoginRequiredMixin, FormView):
    """Formulário unificado de receita/despesa com alternador de tipo.

    Usa o mesmo template do formulário de lançamento, mas apresenta um
    segmentado "Despesa | Receita" no topo. O tipo é decidido pelo campo
    ``kind`` (GET para exibir, POST/JSON para gravar). A categorização usa o
    queryset correto (despesa/receita) conforme o tipo selecionado.
    """

    template_name = "finance/transaction_form.html"
    kind = Transaction.Type.EXPENSE
    title = "Nova movimentação"

    _KINDS = (
        (Transaction.Type.EXPENSE, "Despesa"),
        (Transaction.Type.INCOME, "Receita"),
    )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_form_class(self):
        if self.get_kind() == Transaction.Type.INCOME:
            return IncomeForm
        return ExpenseForm

    def get_kind(self):
        kind = self.request.POST.get("kind") or self.request.GET.get("kind")
        if kind not in (Transaction.Type.INCOME, Transaction.Type.EXPENSE):
            return Transaction.Type.EXPENSE
        return kind

    def get_initial(self):
        initial = super().get_initial()
        initial["kind"] = self.get_kind()
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["kind"] = self.get_kind()
        ctx["unified"] = True
        ctx["kind_choices"] = self._KINDS
        return ctx

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        kind = self.get_kind()
        account = form.cleaned_data["account"]
        transaction = (
            transactions_svc.record_income(
                user=self.request.user,
                account=account,
                amount=form.cleaned_data["amount"],
                date=form.cleaned_data["date"],
                description=form.cleaned_data.get("description") or "",
                category=form.cleaned_data.get("category"),
                notes=form.cleaned_data.get("notes") or "",
            )
            if kind == Transaction.Type.INCOME
            else transactions_svc.record_expense(
                user=self.request.user,
                account=account,
                amount=form.cleaned_data["amount"],
                date=form.cleaned_data["date"],
                description=form.cleaned_data.get("description") or "",
                category=form.cleaned_data.get("category"),
                notes=form.cleaned_data.get("notes") or "",
            )
        )
        balance = balances_svc.account_balance(account)
        label = "Receita" if kind == Transaction.Type.INCOME else "Despesa"
        messages.success(
            self.request,
            f"{label} de {_fmt_brl(transaction.amount)} registrada. "
            f"Saldo novo da conta: {_fmt_brl(balance)}.",
        )
        return redirect(reverse("finance:transaction_list"))


class TransferCreateView(_TransactionBaseFormView):
    form_class = TransferForm
    kind = "transfer"
    title = "Nova transferência"
    template_name = "finance/transfer_form.html"

    def form_valid(self, form):
        transfers_svc.transfer_between(
            user=self.request.user,
            from_account=form.cleaned_data["from_account"],
            to_account=form.cleaned_data["to_account"],
            amount=form.cleaned_data["amount"],
            date=form.cleaned_data["date"],
            notes=form.cleaned_data.get("description") or "",
        )
        messages.success(self.request, "Transferência registrada.")
        return redirect(reverse("finance:transaction_list"))


class TransactionEditView(LoginRequiredMixin, _OwnedObjectMixin, FormView):
    model = Transaction
    template_name = "finance/transaction_form.html"
    form_class = TransactionEditForm

    def get_context_data(self, **kwargs):
        ctx = dict(kwargs)
        transaction = self.get_object()
        ctx["title"] = "Editar lançamento"
        ctx["kind"] = transaction.type
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        transaction = self.get_object()
        kwargs["user"] = self.request.user
        kwargs["kind"] = transaction.type
        return kwargs

    def get_initial(self):
        transaction = self.get_object()
        return {
            "amount": transaction.amount,
            "date": transaction.date,
            "description": transaction.description,
            "notes": transaction.notes,
            "account": transaction.account,
            "category": transaction.category,
        }

    def form_valid(self, form):
        transaction = self.get_object()
        transactions_svc.update_transaction(
            user=self.request.user,
            transaction=transaction,
            amount=form.cleaned_data["amount"],
            date=form.cleaned_data["date"],
            description=form.cleaned_data.get("description") or "",
            notes=form.cleaned_data.get("notes") or "",
            account=form.cleaned_data["account"],
            category=form.cleaned_data.get("category"),
        )
        messages.success(self.request, "Lançamento atualizado.")
        return redirect(reverse("finance:transaction_detail", args=[transaction.pk]))


class TransactionDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        transaction = get_object_or_404(
            Transaction.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        try:
            transactions_svc.delete_transaction(
                user=request.user, transaction=transaction
            )
            messages.success(request, "Lançamento excluído.")
        except Exception as exc:
            messages.error(request, str(exc) or "Não foi possível excluir o lançamento.")
        return redirect(reverse("finance:transaction_list"))


# --------------------------------------------------------------------------- #
# Recorrências
# --------------------------------------------------------------------------- #


class RecurringListView(LoginRequiredMixin, ListView):
    model = RecurringRule
    template_name = "finance/recurring_list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return RecurringRule.objects.for_user(self.request.user).select_related(
            "account", "category", "card"
        ).order_by("-status", "title")


class RecurringCreateView(LoginRequiredMixin, FormView):
    template_name = "finance/recurring_form.html"
    form_class = RecurringForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova recorrência"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        recurrences_svc.create_rule(
            user=self.request.user,
            kind=form.cleaned_data["kind"],
            title=form.cleaned_data["title"],
            amount=form.cleaned_data["amount"],
            frequency=form.cleaned_data["frequency"],
            interval=form.cleaned_data["interval"],
            account=form.cleaned_data.get("account"),
            category=form.cleaned_data.get("category"),
            card=form.cleaned_data.get("card"),
            start_date=form.cleaned_data["start_date"],
            end_date=form.cleaned_data.get("end_date"),
            day_of_month=form.cleaned_data.get("day_of_month"),
            weekday=form.cleaned_data.get("weekday"),
        )
        messages.success(self.request, "Recorrência criada.")
        return redirect(reverse("finance:recurring_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class RecurringEditView(LoginRequiredMixin, _OwnedObjectMixin, FormView):
    model = RecurringRule
    template_name = "finance/recurring_form.html"
    form_class = RecurringForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar recorrência"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        rule = self.get_object()
        return {
            "kind": rule.kind,
            "title": rule.title,
            "amount": rule.amount,
            "frequency": rule.frequency,
            "interval": rule.interval,
            "account": rule.account,
            "category": rule.category,
            "card": rule.card,
            "start_date": rule.start_date,
            "end_date": rule.end_date,
            "day_of_month": rule.day_of_month,
            "weekday": rule.weekday,
        }

    def form_valid(self, form):
        rule = self.get_object()
        recurrences_svc.update_rule(
            user=self.request.user,
            rule=rule,
            title=form.cleaned_data["title"],
            amount=form.cleaned_data["amount"],
            frequency=form.cleaned_data["frequency"],
            interval=form.cleaned_data["interval"],
            account=form.cleaned_data.get("account"),
            category=form.cleaned_data.get("category"),
            card=form.cleaned_data.get("card"),
            start_date=form.cleaned_data["start_date"],
            end_date=form.cleaned_data.get("end_date"),
            day_of_month=form.cleaned_data.get("day_of_month"),
            weekday=form.cleaned_data.get("weekday"),
        )
        messages.success(self.request, "Recorrência atualizada.")
        return redirect(reverse("finance:recurring_list"))


class RecurringStatusView(LoginRequiredMixin, View):
    """Pausa, reativa ou encerra uma recorrência."""

    new_status = None

    def post(self, request, *args, **kwargs):
        rule = get_object_or_404(
            RecurringRule.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        recurrences_svc.set_rule_status(
            user=request.user, rule=rule, status=self.new_status
        )
        label = {"pause": "Pausada", "activate": "Reativada", "end": "Encerrada"}
        messages.success(request, f"Recorrência {label.get(self.new_status, 'atualizada')}.")
        return redirect(reverse("finance:recurring_list"))
