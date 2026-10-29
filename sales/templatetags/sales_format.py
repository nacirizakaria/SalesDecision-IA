from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()


@register.filter
def nombre_fr(value, decimals=2):
    """Affiche un nombre au format financier francais, avec espaces et virgule."""
    if value is None or value == '':
        return '—'
    try:
        precision = max(0, int(decimals))
        nombre = Decimal(str(value))
        unite = Decimal('1').scaleb(-precision)
        nombre = nombre.quantize(unite, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return value

    # L'espace fine inseparable maintient un montant lisible sur une seule ligne.
    return format(nombre, f',.{precision}f').replace(',', '\u202f').replace('.', ',')


@register.filter
def entier_fr(value):
    """Affiche un entier avec un separateur de milliers."""
    if value is None or value == '':
        return '—'
    try:
        return format(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP), ',.0f').replace(',', '\u202f')
    except (InvalidOperation, TypeError, ValueError):
        return value
