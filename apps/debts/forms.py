"""Formulários de dívidas e pagamentos.

Convenção do projeto: ``forms.Form`` puro que delega a escrita aos services.
O formulário de pagamento filtra a conta por ``for_user`` para impedir
pagamento com conta de outro usuário.
"""

from django import forms
from django.utils import timezone

from apps.core.forms import BRLField
from apps.finance.models import Account

from .models import Debt


class DebtForm(forms.Form):
    name = forms.CharField(
        label="Nome da dívida", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Empréstimo do banco"}),
    )
    type = forms.ChoiceField(label="Tipo", choices=Debt.Type.choices)
    total_amount = BRLField(
        label="Valor total (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    interest_rate = forms.DecimalField(
        label="Taxa de juros (% a.m., opcional)", required=False,
        max_digits=6, decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "Ex.: 1.99"}),
    )
    start_date = forms.DateField(
        label="Data inicial (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="Vencimento (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    creditor = forms.CharField(
        label="Credor", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Banco X (opcional)"}),
    )

    def clean_interest_rate(self):
        value = self.cleaned_data.get("interest_rate")
        if value is not None and value < 0:
            raise forms.ValidationError("A taxa não pode ser negativa.")
        return value

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "O vencimento deve ser após a data inicial.")
        return cleaned


class DebtPaymentForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Conta de pagamento", queryset=Account.objects.none(),
    )
    amount = BRLField(
        label="Valor do pagamento (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    date = forms.DateField(
        label="Data", widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = (
                Account.objects.for_user(user)
                .filter(status=Account.Status.ACTIVE)
                .order_by("name")
            )
            self.fields["date"].initial = timezone.localdate()
