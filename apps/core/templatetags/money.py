"""Filtros de template para valores monetários do FINTECPESSOAL.

Dinheiro é inteiro em centavos (decisão D10); estes filtros apenas formatam
para exibição (R$ 1.234,56), sem alterar o valor armazenado.
"""

from django import template

register = template.Library()


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
