from django import template
from django.template.defaultfilters import floatformat

from administracion.services.pagos import (
    NOMBRE_SERVICIO,
    puede_pagarse_online,
    tipo_servicio,
)

register = template.Library()

CLASE_POR_ESTADO = {
    'PENDIENTE': 'text-bg-warning',
    'PAGADO': 'text-bg-success',
    'CUBIERTO_OS': 'text-bg-info',
    'CANCELADO': 'text-bg-secondary',
    'REEMBOLSADO': 'text-bg-dark',
}


@register.filter
def pesos(monto):
    """$ con separador de miles; centavos solo si los hay: $12.500 o
    $12.500,50."""
    if monto is None:
        return ''
    return f'${floatformat(monto, "-2g")}'


@register.filter
def se_puede_pagar(pago):
    """True si el dueño puede pagar online este pago ahora."""
    return pago is not None and puede_pagarse_online(pago)


@register.filter
def clase_estado_pago(estado):
    return CLASE_POR_ESTADO.get(str(estado), 'text-bg-secondary')


@register.filter
def servicio_del_turno(turno):
    """Guardia, Vacunación o Consulta."""
    return NOMBRE_SERVICIO[tipo_servicio(turno)]
