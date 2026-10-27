"""Agenda del veterinario: sus turnos por semana y los de hoy."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from atencion.models import Turno
from atencion.services.turnos import TurnoNoEncontrado


def _turnos_del_veterinario(veterinario):
    # Una consulta para los turnos (con mascota, dueño, nivel y vacuna)
    # y otra para los pagos.
    return (
        Turno.objects.filter(veterinario=veterinario)
        .exclude(estado=Turno.Estado.CANCELADO)
        .select_related(
            'mascota', 'mascota__dueno', 'nivel_urgencia', 'vacuna',
        )
        .prefetch_related('pagos')
    )


def _lunes(semana, hoy):
    try:
        dia = date.fromisoformat(str(semana))
    except ValueError:
        dia = hoy
    return dia - timedelta(days=dia.weekday())


def agenda_semanal(veterinario, semana=None):
    """Turnos del veterinario (sin los cancelados) de la semana que
    contiene `semana` ('AAAA-MM-DD'; por defecto, la actual), de lunes
    a domingo y ordenados por hora."""
    hoy = timezone.localdate()
    lunes = _lunes(semana, hoy)
    desde = timezone.make_aware(datetime.combine(lunes, time(0, 0)))
    hasta = desde + timedelta(days=7)
    turnos = (
        _turnos_del_veterinario(veterinario)
        .filter(fecha_hora__gte=desde, fecha_hora__lt=hasta)
        .order_by('fecha_hora')
    )

    turnos_por_dia = defaultdict(list)
    for turno in turnos:
        turnos_por_dia[timezone.localtime(turno.fecha_hora).date()].append(
            turno
        )

    return {
        'lunes': lunes,
        'dias': [
            {
                'fecha': lunes + timedelta(days=numero),
                'es_hoy': lunes + timedelta(days=numero) == hoy,
                'turnos': turnos_por_dia.get(
                    lunes + timedelta(days=numero), [],
                ),
            }
            for numero in range(7)
        ],
        'es_semana_actual': lunes == hoy - timedelta(days=hoy.weekday()),
        'semana_anterior': (lunes - timedelta(weeks=1)).isoformat(),
        'semana_siguiente': (lunes + timedelta(weeks=1)).isoformat(),
    }


def turnos_de_hoy(veterinario):
    """Turnos de hoy del veterinario (sin los cancelados), en orden."""
    inicio = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(0, 0))
    )
    return list(
        _turnos_del_veterinario(veterinario)
        .filter(fecha_hora__gte=inicio, fecha_hora__lt=inicio + timedelta(1))
        .order_by('fecha_hora')
    )


def obtener_turno_del_veterinario(veterinario, turno_id):
    """El turno si es de este veterinario. Si no, lanza
    TurnoNoEncontrado (la vista responde 404)."""
    try:
        return _turnos_del_veterinario(veterinario).get(pk=turno_id)
    except (Turno.DoesNotExist, ValueError, TypeError):
        raise TurnoNoEncontrado('El turno no existe.')
