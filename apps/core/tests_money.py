"""Testes da conversão monetária robusta (apps.core).

Cobre o parser de texto→centavos (parse_money_to_cents), a formatação
(format_cents), o campo BRLField (aceita '200'/'3000' como reais e formata os
valores iniciais em centavos) e o widget BRLInput.
"""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.core.forms import BRLField, BRLInput
from apps.core.money import format_cents, parse_money_to_cents


class ParseMoneyToCentsTests(SimpleTestCase):
    def test_bare_integer_is_reais(self):
        # "200" = R$ 200,00; "3000" = 3 mil reais; nunca centavos soltos.
        self.assertEqual(parse_money_to_cents("200"), 20000)
        self.assertEqual(parse_money_to_cents("3000"), 300000)
        self.assertEqual(parse_money_to_cents("0"), 0)

    def test_thousands_dots_without_decimal(self):
        self.assertEqual(parse_money_to_cents("2.000"), 200000)
        self.assertEqual(parse_money_to_cents("10.000"), 1000000)
        self.assertEqual(parse_money_to_cents("1.234.567"), 123456700)

    def test_br_decimal_with_comma(self):
        self.assertEqual(parse_money_to_cents("1.234,56"), 123456)
        self.assertEqual(parse_money_to_cents("1234,56"), 123456)
        self.assertEqual(parse_money_to_cents("0,50"), 50)

    def test_us_decimal_with_dot(self):
        # Antes do fix, "1234.56" virava R$ 12.345,60.
        self.assertEqual(parse_money_to_cents("1234.56"), 123456)
        self.assertEqual(parse_money_to_cents("200.50"), 20050)

    def test_single_decimal_digit_is_padded(self):
        self.assertEqual(parse_money_to_cents("1,5"), 150)
        self.assertEqual(parse_money_to_cents("200,5"), 20050)

    def test_sign_and_prefix(self):
        self.assertEqual(parse_money_to_cents("-50,00"), -5000)
        self.assertEqual(parse_money_to_cents("-200"), -20000)
        self.assertEqual(parse_money_to_cents("R$ 200"), 20000)
        self.assertEqual(parse_money_to_cents("R$ 1.234,56"), 123456)

    def test_invalid_inputs_return_none(self):
        for bad in ("abc", "", None, "12,345", "1.234."):
            self.assertIsNone(parse_money_to_cents(bad), bad)

    def test_leading_dot_decimal(self):
        self.assertEqual(parse_money_to_cents(".50"), 50)


class FormatCentsTests(SimpleTestCase):
    def test_br_format(self):
        self.assertEqual(format_cents(123456), "1.234,56")
        self.assertEqual(format_cents(500000), "5.000,00")
        self.assertEqual(format_cents(50), "0,50")
        self.assertEqual(format_cents(-2550), "-25,50")
        self.assertEqual(format_cents(0), "0,00")

    def test_invalid_returns_none(self):
        self.assertIsNone(format_cents(None))
        self.assertIsNone(format_cents("abc"))


class BRLFieldTests(SimpleTestCase):
    def test_to_python_flexible_formats(self):
        field = BRLField()
        self.assertEqual(field.to_python("200"), 20000)
        self.assertEqual(field.to_python("3000"), 300000)
        self.assertEqual(field.to_python("1234.56"), 123456)
        self.assertEqual(field.to_python("1.234,56"), 123456)
        self.assertEqual(field.to_python("1234,56"), 123456)
        self.assertEqual(field.to_python(Decimal("200")), 20000)

    def test_to_python_rejects_garbage(self):
        field = BRLField()
        with self.assertRaises(ValidationError):
            field.to_python("abc")

    def test_min_and_allow_zero(self):
        required = BRLField(min_value_cents=1, allow_zero=False)
        self.assertIsNone(required.to_python(""))
        self.assertEqual(required.to_python("2"), 200)


class BRLInputTests(SimpleTestCase):
    class _Form(forms.Form):
        amount = BRLField()

    class _RequiredForm(forms.Form):
        amount = BRLField(min_value_cents=1, allow_zero=False)

    def test_formats_initial_cents_for_display(self):
        form = self._Form(initial={"amount": 50000})
        html = str(form["amount"])
        self.assertIn('value="500,00"', html)
        # Pré-enche com o formato brasileiro — não com a cifra crua de centavos.
        self.assertNotIn('value="50000"', html)

    def test_marks_input_for_js_mask(self):
        form = self._Form()
        html = str(form["amount"])
        self.assertIn("data-money-input", html)
        self.assertIn('inputmode="decimal"', html)

    def test_post_bare_integer_becomes_reais(self):
        form = self._Form(data={"amount": "3000"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["amount"], 300000)

    def test_edit_post_parses_to_reais(self):
        form = self._Form(data={"amount": "1234.56"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["amount"], 123456)

    def test_preserves_user_text_on_error_post(self):
        form = self._RequiredForm(data={"amount": "zero"})
        self.assertFalse(form.is_valid())
        html = str(form["amount"])
        self.assertIn('value="zero"', html)

    def test_zero_rejected_when_not_allowed(self):
        form = self._RequiredForm(data={"amount": "0"})
        self.assertFalse(form.is_valid())