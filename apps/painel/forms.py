"""Formulários do Painel do Dono — monetização, vendas e código de acesso."""

from django import forms
from django.contrib.auth import get_user_model

from .models import AccessCode, Coupon, MonetizationConfig, Payment, Plan, Subscription

User = get_user_model()


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            "name", "description", "price", "billing_cycle",
            "duration_days", "is_active", "is_featured", "order",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    order = forms.IntegerField(required=False, initial=0)


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code", "discount_type", "discount_value",
            "valid_until", "max_uses", "is_active",
        ]


class GrantSubscriptionForm(forms.Form):
    """Formulário para conceder uma assinatura a um usuário."""

    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(is_active=True))
    notes = forms.CharField(max_length=160, required=False, widget=forms.TextInput(
        attrs={"placeholder": "Observação (opcional)"},
    ))


class RecordPaymentForm(forms.Form):
    """Formulário para registrar um pagamento manual."""

    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Payment.METHOD_CHOICES, initial=Payment.PIX)
    plan = forms.ModelChoiceField(queryset=Plan.objects.all(), required=False)
    coupon_code = forms.CharField(max_length=40, required=False, widget=forms.TextInput(
        attrs={"placeholder": "Cupom (opcional)"},
    ))
    notes = forms.CharField(max_length=160, required=False)


class AccessCodeForm(forms.Form):
    """Geração de códigos de acesso."""

    quantity = forms.IntegerField(min_value=1, max_value=100, initial=1)
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True), required=False,
        help_text="Se definido, o código libera esta assinatura ao resgatar.",
    )
    note = forms.CharField(max_length=120, required=False, widget=forms.TextInput(
        attrs={"placeholder": "Observação (opcional)"},
    ))


class MonetizationForm(forms.Form):
    signup_requires_payment = forms.BooleanField(
        label="Exigir pagamento no cadastro",
        required=False,
        help_text="Quando ativo, novos cadastros só são aceitos com código de acesso.",
    )
    default_plan = forms.ModelChoiceField(
        queryset=Plan.objects.all(), required=False,
        label="Plano padrão",
        help_text="Plano liberado por padrão ao cadastrar com código (quando vinculado).",
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
    support_contact = forms.CharField(
        label="Contato de suporte",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "WhatsApp ou email de suporte"}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if instance is not None:
            self.fields["signup_requires_payment"].initial = instance.signup_requires_payment
            self.fields["default_plan"].initial = instance.default_plan
            self.fields["price_label"].initial = instance.price_label
            self.fields["payment_instructions"].initial = instance.payment_instructions
            self.fields["support_contact"].initial = instance.support_contact
