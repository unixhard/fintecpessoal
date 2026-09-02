"""Formulários de orçamentos.

Convenção do projeto: ``forms.Form`` puro, que captura input e delega a escrita
aos services (nenhuma regra financeira na view/form). Categoria é filtrada por
``for_user`` para impedir seleção de objeto de outro usuário.
"""

from django import forms
from django.utils import timezone

from apps.core.forms import BRLField
from apps.finance.models import Category

from .models import Budget


class BudgetForm(forms.Form):
    kind = forms.ChoiceField(label="Tipo", choices=Budget.Kind.choices)
    category = forms.ModelChoiceField(
        label="Categoria", required=False, queryset=Category.objects.none(),
    )
    period = forms.ChoiceField(
        label="Período", choices=Budget.Period.choices,
    )
    limit_amount = BRLField(
        label="Limite (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    start_date = forms.DateField(
        label="Data inicial (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="Data final (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    is_active = forms.BooleanField(
        label="Ativo", required=False, initial=True,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["category"].queryset = (
                Category.objects.for_user(user)
                .filter(status=Category.Status.ACTIVE, kind=Category.Kind.EXPENSE)
                .order_by("name")
            )

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        category = cleaned.get("category")
        if kind == Budget.Kind.CATEGORY and not category:
            self.add_error("category", "Orçamento por categoria exige uma categoria.")
        if kind == Budget.Kind.GLOBAL and category:
            self.add_error("category", "Orçamento global não deve ter categoria.")
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "A data final deve ser após a inicial.")
        return cleaned
