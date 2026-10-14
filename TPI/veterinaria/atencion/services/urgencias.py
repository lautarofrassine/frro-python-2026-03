"""Flujo de Urgencia: evalua a la mascota con el triage y decide que
hacer segun el nivel. Los turnos de guardia se reservan con
atencion.services.turnos.reservar_turno."""
from datetime import timedelta

from django.utils import timezone

from atencion.models import Turno, Veterinario
from atencion.services.triage import evaluar_mascota
from atencion.services.turnos import (
    DURACION_TURNO,
    ESTADOS_RESERVADO,
    TIPO_GUARDIA,
    HorarioNoDisponible,
    TurnoError,
    reservar_turno,
    turnos_disponibles,
)
from clinica.services.mascotas import (
    MascotaNoEncontrada,
    obtener_mascota_de_dueno,
)

GRAVEDAD_CRITICA = 'critica'
GRAVEDAD_ALTA = 'alta'
GRAVEDAD_LEVE = 'leve'
GRAVEDAD_POR_NIVEL = {
    'CRITICA': GRAVEDAD_CRITICA,
    'ALTA': GRAVEDAD_ALTA,
    'MEDIA': GRAVEDAD_LEVE,
    'BAJA': GRAVEDAD_LEVE,
}
# Si justo ocupan el horario elegido, con cuantos siguientes se prueba.
INTENTOS_DE_RESERVA = 5


def turnos_de_guardia_libres():
    """Proximos horarios libres de veterinarios de GUARDIA, desde el
    proximo turno de 30 minutos y por 24 horas."""
    return turnos_disponibles(
        especialidad=Veterinario.Especialidad.GUARDIA,
        hasta=timezone.now() + timedelta(days=1),
    )


def turno_de_guardia_activo(mascota):
    """El turno de guardia reservado de la mascota que todavia no
    termino, o None. Evita crear otro al recargar o enviar dos veces."""
    return (
        Turno.objects.filter(
            mascota=mascota,
            tipo=TIPO_GUARDIA,
            estado__in=ESTADOS_RESERVADO,
            fecha_hora__gt=timezone.now() - DURACION_TURNO,
        )
        .select_related('veterinario', 'mascota')
        .order_by('fecha_hora')
        .first()
    )


def _reservar_el_primero_libre(dueno, mascota, nivel, horarios):
    for horario in horarios[:INTENTOS_DE_RESERVA]:
        try:
            return reservar_turno(
                dueno,
                mascota.pk,
                horario['veterinario_id'],
                horario['fecha_hora'],
                nivel_urgencia=nivel,
                tipo=TIPO_GUARDIA,
            )
        except HorarioNoDisponible:
            continue
    return None


def plan_de_urgencia(dueno, mascota, nivel):
    """Que hacer con una mascota segun su nivel de urgencia.

    - CRITICA: reserva solo el primer turno de guardia libre.
    - ALTA: propone el primer turno de guardia libre, sin reservarlo.
    - MEDIA / BAJA: nada; se recomienda sacar un turno de consulta.

    Si la mascota ya tiene un turno de guardia activo se devuelve ese y
    no se crea ni se propone otro.

    Devuelve {'gravedad', 'turno', 'turno_propuesto'}; `turno` es el
    turno de guardia reservado (o None si no hay horarios libres).
    """
    plan = {
        'gravedad': GRAVEDAD_POR_NIVEL.get(nivel, GRAVEDAD_LEVE),
        'turno': None,
        'turno_propuesto': None,
    }
    if plan['gravedad'] == GRAVEDAD_LEVE:
        return plan

    plan['turno'] = turno_de_guardia_activo(mascota)
    if plan['turno'] is None:
        libres = turnos_de_guardia_libres()
        if plan['gravedad'] == GRAVEDAD_CRITICA:
            plan['turno'] = _reservar_el_primero_libre(
                dueno, mascota, nivel, libres,
            )
        elif libres:
            plan['turno_propuesto'] = libres[0]
    return plan


def atender_urgencia(dueno, mascota_id, datos_sintomas):
    """Evalua a la mascota (triage) y arma el plan segun el nivel.
    Devuelve el resultado del triage con el plan en 'plan'.

    Lanza MascotaNoEncontrada si la mascota no es del dueño y
    MascotaError si no tiene fecha de nacimiento.
    """
    resultado = evaluar_mascota(dueno, mascota_id, datos_sintomas)
    resultado['plan'] = plan_de_urgencia(
        dueno, resultado['mascota'], resultado['nivel'],
    )
    return resultado


def confirmar_turno_de_guardia(dueno, mascota_id, veterinario_id,
                               fecha_hora):
    """Reserva el turno de guardia propuesto para una urgencia ALTA. Si
    justo lo ocuparon, reserva el siguiente libre. Si la mascota ya
    tiene un turno de guardia activo, devuelve ese. Lanza TurnoError si
    no quedan turnos de guardia."""
    try:
        mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    except MascotaNoEncontrada:
        raise TurnoError(
            'La mascota elegida no existe o no está entre tus mascotas.'
        )
    existente = turno_de_guardia_activo(mascota)
    if existente:
        return existente

    # Solo se elige entre horarios libres de GUARDIA; el propuesto va
    # primero si sigue libre.
    def es_el_propuesto(horario):
        return (
            str(horario['veterinario_id']) == str(veterinario_id)
            and horario['fecha_hora'].isoformat() == str(fecha_hora)
        )

    libres = sorted(
        turnos_de_guardia_libres(), key=lambda h: not es_el_propuesto(h),
    )
    turno = _reservar_el_primero_libre(dueno, mascota, 'ALTA', libres)
    if turno is None:
        raise TurnoError(
            'No quedan turnos de guardia libres. Vení igual a la guardia: '
            'te atendemos.'
        )
    return turno
