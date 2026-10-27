from django import template
from django.utils import timezone

from atencion.services.turnos import puede_cancelarse

register = template.Library()


@register.filter
def ultimo_pago(turno):
    """El pago mas reciente del turno, o None si no tiene. Usa los
    pagos ya precargados por el service (no hace otra consulta)."""
    pagos = sorted(turno.pagos.all(), key=lambda pago: pago.pk)
    return pagos[-1] if pagos else None


@register.filter
def se_puede_cancelar(turno):
    """True si el dueño todavia puede cancelar el turno."""
    return puede_cancelarse(turno)


@register.filter
def es_hoy(fecha_hora):
    """True si la fecha (en hora local) es la de hoy."""
    return timezone.localtime(fecha_hora).date() == timezone.localdate()


TIPOS_CON_URGENCIA = ('Guardia', 'Triage')
CLASE_POR_NIVEL = {
    'CRITICA': 'text-bg-danger',
    'ALTA': 'bg-alta',
    'MEDIA': 'text-bg-warning',
    'BAJA': 'text-bg-success',
}


@register.filter
def es_de_guardia(turno):
    """True si el turno salio de Urgencia (su nivel de urgencia importa).
    Los de consulta tambien tienen nivel (BAJA por defecto), pero no se
    muestra."""
    return turno.tipo in TIPOS_CON_URGENCIA


@register.filter
def clase_urgencia(nivel):
    """Clase de color del badge del nivel de urgencia."""
    return CLASE_POR_NIVEL.get(str(nivel), 'text-bg-secondary')
