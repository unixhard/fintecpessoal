"""Formulários de metas financeiras.

Convenção do projeto: ``forms.Form`` puro que delega a escrita aos services.
A meta não expõe ``current_amount`` nas telas de criação/edição — o acumulado
só muda por contribuição explícita (regra de negócio), mantendo a
contabilidade auditável e consistente.
"""

from django import forms

from apps.core.forms import BRLField

from .models import Goal


class GoalForm(forms.Form):
    name = forms.CharField(
        label="Nome da meta", max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Reserva de emergência"}),
    )
    target_amount = BRLField(
        label="Valor objetivo (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
    target_date = forms.DateField(
        label="Data objetivo (opcional)", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    priority = forms.ChoiceField(
        label="Prioridade", choices=Goal.Priority.choices,
    )
    notes = forms.CharField(
        label="Observações", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Opcional"}),
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para a meta.")
        return name


class GoalContributionForm(forms.Form):
    amount = BRLField(
        label="Valor do aporte (R$)", min_value_cents=1, allow_zero=False,
        widget=forms.TextInput(attrs={"placeholder": "0,00", "inputmode": "decimal"}),
    )
