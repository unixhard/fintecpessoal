"""Formulários financeiros (contas, categorias, lançamentos, transferências,
recorrências).

Convenção do projeto: formulários usam ``forms.Form`` (não ModelForm) e delegam
a escrita à camada de serviços (regra 16 — nenhuma regra financeira na view).
Campos de referência (conta/categoria/cartão) são preenchidos com querysets
isolados por usuário via ``for_user``.
"""

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.core.forms import BRLField

from .models import Account, Category, ClassificationRule, Merchant, RecurringRule, Transaction


def _active_accounts_choices(user):
    return Account.objects.for_user(user).filter(
        status=Account.Status.ACTIVE
    )


def _active_categories_choices(user, kind):
    return Category.objects.for_user(user).filter(
        status=Category.Status.ACTIVE, kind=kind
    )


# --------------------------------------------------------------------------- #
# Contas
# --------------------------------------------------------------------------- #


class AccountCreateForm(forms.Form):
    name = forms.CharField(
        label="Nome da conta", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Conta do dia a dia"}),
    )
    type = forms.ChoiceField(label="Tipo de conta", choices=Account.Type.choices)
    institution = forms.CharField(
        label="Instituição", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Banco X (opcional)"}),
    )
    initial_balance = BRLField(
        label="Saldo inicial (R$)", required=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para a conta.")
        return name


class AccountEditForm(forms.Form):
    name = forms.CharField(
        label="Nome da conta", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Conta do dia a dia"}),
    )
    type = forms.ChoiceField(label="Tipo de conta", choices=Account.Type.choices)
    institution = forms.CharField(
        label="Instituição", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Banco X (opcional)"}),
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para a conta.")
        return name


# --------------------------------------------------------------------------- #
# Categorias
# --------------------------------------------------------------------------- #


class CategoryForm(forms.Form):
    name = forms.CharField(
        label="Nome", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Mercado"}),
    )
    kind = forms.ChoiceField(label="Tipo", choices=Category.Kind.choices)
    parent = forms.ModelChoiceField(
        label="Categoria pai (opcional)",
        required=False,
        queryset=Category.objects.none(),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["parent"].queryset = Category.objects.for_user(user).filter(
                status=Category.Status.ACTIVE
            ).exclude(parent__isnull=False)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para a categoria.")
        return name


# --------------------------------------------------------------------------- #
# Lançamentos (receita / despesa / transferência / edição)
# --------------------------------------------------------------------------- #


class _TransactionFormBase(forms.Form):
    amount = BRLField(
        label="Valor (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    date = forms.DateField(
        label="Data", widget=forms.DateInput(attrs={"type": "date"}),
    )
    description = forms.CharField(
        label="Descrição", max_length=200, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Opcional"}),
    )
    notes = forms.CharField(
        label="Observações", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = _active_accounts_choices(user)
        if "date" in self.fields:
            self.fields["date"].initial = timezone.localdate()


class IncomeForm(_TransactionFormBase):
    account = forms.ModelChoiceField(
        label="Conta", queryset=Account.objects.none(),
    )
    category = forms.ModelChoiceField(
        label="Categoria", required=False, queryset=Category.objects.none(),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if user is not None:
            self.fields["category"].queryset = _active_categories_choices(
                user, Category.Kind.INCOME
            )


class ExpenseForm(_TransactionFormBase):
    account = forms.ModelChoiceField(
        label="Conta", queryset=Account.objects.none(),
    )
    category = forms.ModelChoiceField(
        label="Categoria", required=False, queryset=Category.objects.none(),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if user is not None:
            self.fields["category"].queryset = _active_categories_choices(
                user, Category.Kind.EXPENSE
            )


class TransferForm(forms.Form):
    from_account = forms.ModelChoiceField(
        label="Conta de origem", queryset=Account.objects.none(),
    )
    to_account = forms.ModelChoiceField(
        label="Conta de destino", queryset=Account.objects.none(),
    )
    amount = BRLField(
        label="Valor (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    date = forms.DateField(
        label="Data", widget=forms.DateInput(attrs={"type": "date"}),
    )
    description = forms.CharField(
        label="Descrição", max_length=200, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Opcional"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["from_account"].queryset = _active_accounts_choices(user)
            self.fields["to_account"].queryset = _active_accounts_choices(user)
            self.fields["date"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        frm = cleaned.get("from_account")
        to = cleaned.get("to_account")
        if frm and to and frm.pk == to.pk:
            self.add_error("to_account", "Origem e destino devem ser contas distintas.")
        return cleaned


class TransactionEditForm(_TransactionFormBase):
    account = forms.ModelChoiceField(
        label="Conta", queryset=Account.objects.none(),
    )
    category = forms.ModelChoiceField(
        label="Categoria", required=False, queryset=Category.objects.none(),
    )

    def __init__(self, *args, user=None, kind=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.kind = kind
        if user is not None:
            self.fields["category"].queryset = _active_categories_choices(
                user, kind
            )


# --------------------------------------------------------------------------- #
# Recorrências
# --------------------------------------------------------------------------- #


class RecurringForm(forms.Form):
    kind = forms.ChoiceField(
        label="Tipo", choices=RecurringRule.Kind.choices,
    )
    title = forms.CharField(
        label="Título", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Aluguel"}),
    )
    amount = BRLField(
        label="Valor (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    frequency = forms.ChoiceField(
        label="Frequência", choices=RecurringRule.Frequency.choices,
    )
    interval = forms.IntegerField(
        label="A cada (períodos)", min_value=1, initial=1,
    )
    account = forms.ModelChoiceField(
        label="Conta", required=False, queryset=Account.objects.none(),
    )
    card = forms.ModelChoiceField(
        label="Cartão", required=False, queryset=Account.objects.none(),
    )
    category = forms.ModelChoiceField(
        label="Categoria", required=False, queryset=Category.objects.none(),
    )
    start_date = forms.DateField(
        label="Data inicial", widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="Data final (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    day_of_month = forms.IntegerField(
        label="Dia do mês", required=False, min_value=1, max_value=31,
    )
    weekday = forms.IntegerField(
        label="Dia da semana (0=seg ... 6=dom)", required=False,
        min_value=0, max_value=6,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = _active_accounts_choices(user)
            self.fields["category"].queryset = Category.objects.for_user(user)
        # Card queryset definido no import da view (evita import circular).
        from apps.cards.models import CreditCard

        self.fields["card"].queryset = CreditCard.objects.for_user(user).filter(
            status=CreditCard.Status.ACTIVE
        ) if user is not None else CreditCard.objects.none()
        if "start_date" in self.fields:
            self.fields["start_date"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "A data final deve ser após a inicial.")
        kind = cleaned.get("kind")
        account = cleaned.get("account")
        card = cleaned.get("card")
        if kind == RecurringRule.Kind.EXPENSE and not (account or card):
            self.add_error("account", "Despesa recorrente exige conta ou cartão.")
        if kind == RecurringRule.Kind.INCOME and not account:
            self.add_error("account", "Receita recorrente exige uma conta.")
        return cleaned


# --------------------------------------------------------------------------- #
# Regras de classificação (Ordem 18 — FASE 6/12)
# --------------------------------------------------------------------------- #


class ClassificationRuleForm(forms.Form):
    name = forms.CharField(
        label="Nome", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Uber"}),
    )
    condition_type = forms.ChoiceField(
        label="Condição", choices=ClassificationRule.ConditionType.choices,
    )
    pattern = forms.CharField(
        label="Texto da descrição", max_length=200, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: UBER *TRIP (case-insensitive)"}),
    )
    merchant = forms.ModelChoiceField(
        label="Estabelecimento", required=False,
        queryset=Merchant.objects.none(),
    )
    category = forms.ModelChoiceField(
        label="Categoria", required=False,
        queryset=Category.objects.none(),
    )
    category_name = forms.CharField(
        label="Nome da categoria (quando não FK)", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Transporte"}),
    )
    kind = forms.ChoiceField(
        label="Tipo de movimentação", choices=ClassificationRule.Kind.choices,
    )
    priority = forms.IntegerField(
        label="Prioridade (menor = maior)", min_value=1, initial=100,
        widget=forms.NumberInput(attrs={"placeholder": "100"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["category"].queryset = Category.objects.for_user(user).filter(
                status=Category.Status.ACTIVE,
            )
            self.fields["merchant"].queryset = Merchant.objects.filter(
                Q(owner=user) | Q(owner__isnull=True)
            )

    def clean(self):
        cleaned = super().clean()
        cond = cleaned.get("condition_type")
        if cond == ClassificationRule.ConditionType.CONTAINS and not (cleaned.get("pattern") or "").strip():
            self.add_error("pattern", "Informe o texto que a descrição deve conter.")
        if cond == ClassificationRule.ConditionType.MERCHANT and not cleaned.get("merchant"):
            self.add_error("merchant", "Selecione o estabelecimento.")
        cat = cleaned.get("category")
        cat_name = (cleaned.get("category_name") or "").strip()
        if not cat and not cat_name:
            self.add_error("category", "Informe a categoria ou o nome da categoria.")
        return cleaned


class ReviewCorrectionForm(forms.Form):
    """Formulário de correção individual na fila de revisão."""

    transaction_id = forms.IntegerField(widget=forms.HiddenInput)
    category = forms.ModelChoiceField(
        label="Categoria", required=False,
        queryset=Category.objects.none(),
        widget=forms.Select(attrs={"class": "w-full rounded-lg border border-surface-200 bg-white px-3 py-2 text-sm dark:border-surface-700 dark:bg-surface-900"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["category"].queryset = Category.objects.for_user(user).filter(
                status=Category.Status.ACTIVE,
            )
