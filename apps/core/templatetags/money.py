"""Filtros de template para valores monetários do FINTECPESSOAL.

Dinheiro é inteiro em centavos (decisão D10); estes filtros apenas formatam
para exibição (R$ 1.234,56), sem alterar o valor armazenado.
"""

from django import template

from apps.core.money import format_cents

register = template.Library()


@register.filter
def brlvalue(value, arg=None):
    """Formata centavos (int) como '1.234,56' para valor de input monetário.

    Se ``value`` já for texto (digitação retornada em POST), passa inalterado;
    se for inteiro de centavos (valor inicial de edição), formata para exibição.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        formatted = format_cents(value)
        if formatted is not None:
            return formatted
    return value


@register.filter
def centavos(value):
    """Formata um valor em centavos (int) como 'R$ 1.234,56'."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if value < 0 else ""
    value = abs(value)
    reais, cents = divmod(value, 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cents:02d}"
