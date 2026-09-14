"""Formulários do Painel do Dono."""

from django import forms

from .models import MonetizationConfig


class MonetizationForm(forms.Form):
    signup_requires_payment = forms.BooleanField(
        label="Exigir pagamento no cadastro",
        required=False,
        help_text="Quando ativo, novos cadastros só são aceitos com código de acesso.",
    )
    price_label = forms.CharField(
        label="Texto de preço",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: R$ 9,90 / mês"}),
    )
    payment_instructions = forms.CharField(
        label="Instruções de pagamento",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Como o visitante paga para obter o código de acesso."}
        ),
    )

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if instance is not None:
            self.fields["signup_requires_payment"].initial = instance.signup_requires_payment
            self.fields["price_label"].initial = instance.price_label
            self.fields["payment_instructions"].initial = instance.payment_instructions