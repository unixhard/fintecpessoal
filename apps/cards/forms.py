"""Formulários de cartão de crédito, compras e faturas.

Delegam a escrita à camada de serviços (regra 16). Querysets isolados por
usuário via ``for_user``.
"""

from django import forms
from django.utils import timezone

from apps.core.forms import BRLField
from apps.finance.models import Account

from .models import CreditCard


class CardCreateForm(forms.Form):
    name = forms.CharField(
        label="Nome", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Cartão Black"}),
    )
    institution = forms.CharField(
        label="Instituição", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Banco X (opcional)"}),
    )
    limit = BRLField(
        label="Limite (R$)", required=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    closing_day = forms.IntegerField(
        label="Dia de fechamento", min_value=1, max_value=31, initial=1,
    )
    due_day = forms.IntegerField(
        label="Dia de vencimento", min_value=1, max_value=31, initial=10,
    )
    payment_account = forms.ModelChoiceField(
        label="Conta de pagamento", required=False, queryset=Account.objects.none(),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["payment_account"].queryset = Account.objects.for_user(
                user
            ).filter(status=Account.Status.ACTIVE)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para o cartão.")
        return name


class CardEditForm(CardCreateForm):
    """Mesma estrutura do formulário de criação, para edição."""


class PurchaseForm(forms.Form):
    card = forms.ModelChoiceField(
        label="Cartão", queryset=CreditCard.objects.none(),
    )
    description = forms.CharField(
        label="Descrição", max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Notebook"}),
    )
    total_amount = BRLField(
        label="Valor total (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    installment_count = forms.IntegerField(
        label="Número de parcelas", min_value=1, initial=1,
        help_text="1 = à vista; >1 = parcelada.",
    )
    first_due_date = forms.DateField(
        label="Primeira parcela / vencimento",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["card"].queryset = CreditCard.objects.for_user(user).filter(
                status=CreditCard.Status.ACTIVE
            )
            self.fields["first_due_date"].initial = timezone.localdate()


class InvoicePayForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Conta de pagamento", queryset=Account.objects.none(),
    )
    date = forms.DateField(
        label="Data do pagamento",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.for_user(user).filter(
                status=Account.Status.ACTIVE
            )
            self.fields["date"].initial = timezone.localdate()
