"""Pagos de los turnos (RF07).

Al reservar, crear_pago_de_turno calcula el precio (el del veterinario
vigente en la fecha del turno), la cobertura de la obra social del dueño
y el monto a pagar. Esos montos quedan fijos: cambios posteriores en la
obra social, en las del veterinario o en sus precios no los modifican.

El dueño paga online (administracion.services.mercadopago_service) o en
la clinica, donde el veterinario del turno registra el cobro en efectivo.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from administracion.models import Pago
from atencion.models import Turno, Veterinario
from atencion.services.precios import precio_vigente
from clinica.models import Dueno

CENTAVOS = Decimal('0.01')
CERO = Decimal('0')

# Tipos de servicio (para ver que cubre la obra social).
GUARDIA = 'GUARDIA'
VACUNACION = 'VACUNACION'
CONSULTA = 'CONSULTA'
NOMBRE_SERVICIO = {
    GUARDIA: 'Guardia',
    VACUNACION: 'Vacunación',
    CONSULTA: 'Consulta',
}
CAMPO_COBERTURA = {
    GUARDIA: 'cubre_guardia',
    VACUNACION: 'cubre_vacunacion',
    CONSULTA: 'cubre_consultas',
}

SIN_OBRA_SOCIAL = 'Sin obra social'
VETERINARIO_NO_ATIENDE = 'Este veterinario no atiende tu obra social'
SERVICIO_NO_CUBIERTO = 'Tu obra social no cubre este servicio'
TOPE_ALCANZADO = 'Alcanzaste el tope mensual de tu obra social'

# Pagos cuya cobertura cuenta para el tope mensual.
ESTADOS_QUE_USAN_TOPE = (
    Pago.Estado.PENDIENTE, Pago.Estado.PAGADO, Pago.Estado.CUBIERTO_OS,
)


class PagoError(Exception):
    """Regla de pagos violada. El mensaje es para mostrarselo al usuario."""


class PagoNoEncontrado(PagoError):
    """El pago no existe o no es de quien lo pide (la vista da 404)."""


def _centavos(monto):
    return Decimal(monto).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------
# Calculo
# ---------------------------------------------------------------------

def tipo_servicio(turno):
    """GUARDIA (veterinario de guardia), VACUNACION (turno con vacuna) o
    CONSULTA (el resto)."""
    if turno.veterinario.especialidad == Veterinario.Especialidad.GUARDIA:
        return GUARDIA
    if turno.vacuna_id:
        return VACUNACION
    return CONSULTA


def _rango_del_mes(anio, mes):
    inicio = timezone.make_aware(datetime(anio, mes, 1))
    if mes == 12:
        fin = timezone.make_aware(datetime(anio + 1, 1, 1))
    else:
        fin = timezone.make_aware(datetime(anio, mes + 1, 1))
    return inicio, fin


def cobertura_usada_en_mes(dueno, anio, mes):
    """Suma de lo que cubrio la obra social en los pagos PENDIENTE,
    PAGADO y CUBIERTO_OS del dueño cuyos turnos caen en ese mes."""
    inicio, fin = _rango_del_mes(anio, mes)
    total = Pago.objects.filter(
        turno__mascota__dueno=dueno,
        turno__fecha_hora__gte=inicio,
        turno__fecha_hora__lt=fin,
        estado__in=ESTADOS_QUE_USAN_TOPE,
    ).aggregate(total=Sum('monto_cubierto_os'))['total']
    return total or CERO


def tope_restante_del_mes(dueno, fecha=None):
    """Cuanto le queda del tope mensual de su obra social en el mes de
    `fecha` (por defecto, este mes). None si no tiene obra social."""
    obra_social = dueno.obra_social
    if obra_social is None:
        return None
    fecha = fecha or timezone.localdate()
    usada = cobertura_usada_en_mes(dueno, fecha.year, fecha.month)
    return max(obra_social.tope_mensual - usada, CERO)


def calcular_cobertura(dueno, turno, precio):
    """Devuelve (monto_cubierto, monto_a_pagar, motivo_sin_cobertura).

    La obra social cubre si el veterinario del turno la atiende y si
    cubre el tipo de servicio: precio x porcentaje / 100, limitado a lo
    que queda del tope mensual (en el mes del turno). motivo es None si
    cubre algo, o el texto que explica por que no."""
    precio = _centavos(precio)
    obra_social = dueno.obra_social
    if obra_social is None:
        return CERO, precio, SIN_OBRA_SOCIAL
    atiende = turno.veterinario.obras_sociales.filter(
        pk=obra_social.pk,
    ).exists()
    if not atiende:
        return CERO, precio, VETERINARIO_NO_ATIENDE
    if not getattr(obra_social, CAMPO_COBERTURA[tipo_servicio(turno)]):
        return CERO, precio, SERVICIO_NO_CUBIERTO

    fecha = timezone.localtime(turno.fecha_hora).date()
    restante = tope_restante_del_mes(dueno, fecha)
    if restante <= 0:
        return CERO, precio, TOPE_ALCANZADO
    cubierto = _centavos(precio * obra_social.porcentaje_cobertura / 100)
    cubierto = max(min(cubierto, restante, precio), CERO)
    return cubierto, precio - cubierto, None


# ---------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------

def crear_pago_de_turno(turno):
    """Crea el pago de un turno recien reservado (lo llama
    reservar_turno, dentro de su transaccion). Si la obra social cubre
    todo, queda CUBIERTO_OS; si no, PENDIENTE."""
    with transaction.atomic():
        # Bloquea al dueño: dos reservas simultaneas no pueden usar dos
        # veces lo que queda del tope mensual.
        dueno = (
            Dueno.objects.select_for_update()
            .select_related('obra_social')
            .get(pk=turno.mascota.dueno_id)
        )
        precio = precio_vigente(turno.veterinario, turno.fecha_hora)
        cubierto, a_pagar, motivo = calcular_cobertura(dueno, turno, precio)
        return Pago.objects.create(
            turno=turno,
            monto_total=_centavos(precio),
            monto_cubierto_os=cubierto,
            monto_a_pagar=a_pagar,
            detalle_cobertura=motivo or '',
            estado=(
                Pago.Estado.CUBIERTO_OS if a_pagar == 0
                else Pago.Estado.PENDIENTE
            ),
        )


def cancelar_pago_de_turno(turno):
    """Al cancelar un turno: PENDIENTE y CUBIERTO_OS pasan a CANCELADO y
    PAGADO a REEMBOLSADO (la devolucion la gestiona la clinica; no se
    hace el reembolso en Mercado Pago). Devuelve cuantos pagos quedaron
    REEMBOLSADO."""
    pagos = turno.pagos.select_for_update()
    pagos.filter(
        estado__in=(Pago.Estado.PENDIENTE, Pago.Estado.CUBIERTO_OS),
    ).update(estado=Pago.Estado.CANCELADO)
    return pagos.filter(estado=Pago.Estado.PAGADO).update(
        estado=Pago.Estado.REEMBOLSADO,
    )


def numero_de_comprobante(pago):
    return f'CV-{pago.pk:06d}'


def marcar_pagado(pago, metodo, mp_payment_id=''):
    """Marca el pago (ya bloqueado y PENDIENTE) como PAGADO y le asigna
    su comprobante. Uso interno de este modulo y de mercadopago_service."""
    pago.estado = Pago.Estado.PAGADO
    pago.metodo = metodo
    pago.fecha_pago = timezone.now()
    pago.numero_comprobante = numero_de_comprobante(pago)
    pago.mp_payment_id = mp_payment_id or ''
    pago.save(update_fields=[
        'estado', 'metodo', 'fecha_pago', 'numero_comprobante',
        'mp_payment_id',
    ])
    return pago


def registrar_cobro_efectivo(veterinario, pago_id):
    """El veterinario del turno registra que cobro en la clinica. Lanza
    PagoNoEncontrado si el pago no es de un turno suyo y PagoError si
    no esta pendiente."""
    with transaction.atomic():
        try:
            pago = (
                Pago.objects.select_for_update()
                .get(pk=pago_id, turno__veterinario=veterinario)
            )
        except (Pago.DoesNotExist, ValueError, TypeError):
            raise PagoNoEncontrado('El pago no existe.')
        if pago.estado != Pago.Estado.PENDIENTE:
            raise PagoError('Solo se pueden cobrar pagos pendientes.')
        return marcar_pagado(pago, Pago.Metodo.EFECTIVO)


# ---------------------------------------------------------------------
# Consultas del dueño
# ---------------------------------------------------------------------

def _pagos_de_dueno(dueno):
    return Pago.objects.filter(turno__mascota__dueno=dueno).select_related(
        'turno', 'turno__mascota', 'turno__veterinario', 'turno__vacuna',
    )


def obtener_pago_de_dueno(dueno, pago_id):
    """El pago si es de un turno de una mascota del dueño. Si no, lanza
    PagoNoEncontrado."""
    try:
        return _pagos_de_dueno(dueno).get(pk=pago_id)
    except (Pago.DoesNotExist, ValueError, TypeError):
        raise PagoNoEncontrado('El pago no existe.')


def motivo_para_no_pagar_online(pago):
    """None si se puede pagar online; si no, el motivo."""
    if pago.estado == Pago.Estado.PAGADO:
        return 'Este pago ya está pagado.'
    if pago.estado == Pago.Estado.CUBIERTO_OS:
        return 'Este turno está cubierto por tu obra social.'
    if pago.estado != Pago.Estado.PENDIENTE:
        return 'Este pago ya no está pendiente.'
    if pago.turno.estado == Turno.Estado.CANCELADO:
        return 'El turno fue cancelado.'
    if pago.turno.fecha_hora <= timezone.now():
        return 'El turno ya pasó: se paga en la clínica.'
    if pago.monto_a_pagar <= 0:
        return 'No hay nada para pagar.'
    return None


def puede_pagarse_online(pago):
    return motivo_para_no_pagar_online(pago) is None


def validar_pago_online(pago):
    motivo = motivo_para_no_pagar_online(pago)
    if motivo:
        raise PagoError(motivo)


def pagos_del_dueno(dueno):
    """Para "Mis pagos": los pendientes (del turno mas cercano al mas
    lejano) y el historial (del mas reciente al mas viejo)."""
    pagos = list(_pagos_de_dueno(dueno))
    pendientes = sorted(
        (p for p in pagos if p.estado == Pago.Estado.PENDIENTE),
        key=lambda p: p.turno.fecha_hora,
    )
    historial = sorted(
        (p for p in pagos if p.estado != Pago.Estado.PENDIENTE),
        key=lambda p: (p.fecha_pago or p.fecha),
        reverse=True,
    )
    return {'pendientes': pendientes, 'historial': historial}


def pago_de_turno(turno):
    """El pago mas reciente del turno, o None."""
    return turno.pagos.order_by('-pk').first()


def turno_con_devolucion_pendiente(turno):
    """True si el turno tenia un pago PAGADO que paso a REEMBOLSADO."""
    return turno.pagos.filter(estado=Pago.Estado.REEMBOLSADO).exists()
