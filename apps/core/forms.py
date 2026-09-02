"""Campos de formulário reutilizáveis do núcleo (ex.: valores monetários).

A conversão reais→centavos é uma preocupação de APRESENTAÇÃO na fronteira do
formulário; a regra financeira (inteiro em centavos, ownership) permanece na
camada de serviços (decisão D10 / regra 16). Estes campos apenas traduzem o
texto digitado (ex.: '1.500,00') em centavos inteiros.
"""

import decimal
from decimal import Decimal

from django import forms


class BRLField(forms.Field):
    """Campo monetário que recebe reais (ex.: '1.500,00') e devolve centavos int.

    Permite valor zero ou negativo quando ``allow_negative``; por padrão é
    não-negativo (>= 0).
    """

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
        if not isinstance(value, str):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        value = value.strip()
        if not value:
            return 0 if self.min_value_cents == 0 else None
        normalized = value.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(normalized)
        except (TypeError, ValueError, decimal.InvalidOperation):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return int((amount * 100).to_integral_value(rounding=decimal.ROUND_HALF_UP))

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
