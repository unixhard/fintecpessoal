"""Campos de formulário reutilizáveis do núcleo (ex.: valores monetários).

A conversão reais→centavos é uma preocupação de APRESENTAÇÃO na fronteira do
formulário; a regra financeira (inteiro em centavos, ownership) permanece na
camada de serviços (decisão D10 / regra 16). Estes campos apenas traduzem o
texto digitado (ex.: '1.500,00', '200', '3000') em centavos inteiros.
"""

from decimal import Decimal

from django import forms

from .money import format_cents, parse_money_to_cents


class BRLInput(forms.TextInput):
    """TextInput monetário com formatação automática '1.500,00'.

    - Em GET/edição, formata o valor inicial (int em centavos) como
      '1.500,00' em vez de mostrar '150000'.
    - Em POST com erro, preserva o texto digitado pelo usuário (str).
    - Carrega ``data-money-input`` para a máscara JS (static/js/app.js) que
      corrige a digitação em tempo real (ex.: '3000' → '3.000,00').
    """

    default_attrs = {"placeholder": "0,00", "inputmode": "decimal",
                     "data-money-input": "true"}

    def __init__(self, attrs=None):
        merged = dict(self.default_attrs)
        if attrs:
            merged.update(attrs)
        super().__init__(merged)

    def format_value(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            formatted = format_cents(value)
            if formatted is not None:
                return formatted
        return value


class BRLField(forms.Field):
    """Campo monetário que recebe reais (ex.: '1.500,00') e devolve centavos int.

    Aceita formatos flexíveis: '200' e '3000' viram R$ 200,00 e R$ 3.000,00;
    '1.234,56', '1234,56' e '1234.56' viram 123456 centavos.
    Permite valor zero ou negativo quando ``allow_negative``; por padrão é
    não-negativo (>= 0).
    """

    widget = BRLInput

    default_error_messages = {
        "invalid": "Informe um valor monetário válido (ex.: 1.500,00).",
        "negative": "O valor não pode ser negativo.",
        "positive": "O valor deve ser maior que zero.",
    }

    def __init__(self, *, min_value_cents=0, allow_zero=True, **kwargs):
        super().__init__(**kwargs)
        self.min_value_cents = min_value_cents
        self.allow_zero = allow_zero

    def to_python(self, value):
        if value in self.empty_values:
            return 0 if self.min_value_cents == 0 else None
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        value = value.strip()
        if not value:
            return 0 if self.min_value_cents == 0 else None
        cents = parse_money_to_cents(value)
        if cents is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return cents

    def validate(self, value):
        super().validate(value)
        if value is None:
            return
        if value < self.min_value_cents:
            if self.min_value_cents > 0:
                raise forms.ValidationError(
                    self.error_messages["positive"], code="positive"
                )
            raise forms.ValidationError(
                self.error_messages["negative"], code="negative"
            )
        if not self.allow_zero and value == 0:
            raise forms.ValidationError(
                self.error_messages["positive"], code="positive"
            )
