from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def ultimo_pago(turno):
    """El pago mas reciente del turno, o None si no tiene. Usa los
    pagos ya precargados por el service (no hace otra consulta)."""
    pagos = sorted(turno.pagos.all(), key=lambda pago: pago.pk)
    return pagos[-1] if pagos else None


@register.filter
def es_hoy(fecha_hora):
    """True si la fecha (en hora local) es la de hoy."""
    return timezone.localtime(fecha_hora).date() == timezone.localdate()
