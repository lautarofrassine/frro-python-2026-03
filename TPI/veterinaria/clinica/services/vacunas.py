import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.core.exceptions import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
)
from django.db import transaction
from django.utils import timezone

from atencion.models import Turno, Veterinario
from atencion.services.turnos import (
    crear_turno_manual,
    turnos_disponibles_por_especialidad,
)
from clinica.models import Mascota, Vacuna
from clinica.services.mascotas import obtener_mascota_de_dueno

# Un turno de vacunacion es un turno comun (lo crea la funcion de
# reserva existente, crear_turno_manual) marcado con la vacuna.
TIPO_TURNO_VACUNACION = 'Vacunación'
# El turno exige un nivel de urgencia; una vacuna es una visita
# programada, no una urgencia.
NIVEL_URGENCIA_VACUNACION = 'BAJA'
# Con cuantos dias de anticipacion se puede reservar.
DIAS_ADELANTE = 14

_PERRO = Mascota.Especie.PERRO
_GATO = Mascota.Especie.GATO

# (nombre, nombre_corto, especie, descripcion para el dueño)
VACUNAS_INICIALES = [
    ('Séxtuple', 'Séxtuple', _PERRO,
     'Protege contra moquillo, parvovirus, hepatitis, leptospirosis y '
     'otras enfermedades graves del perro.'),
    ('Antirrábica', 'Antirrábica', _PERRO,
     'Previene la rabia. Es obligatoria y se refuerza todos los años.'),
    ('Tos de las perreras', 'Tos perreras', _PERRO,
     'Previene la traqueobronquitis infecciosa, muy contagiosa entre '
     'perros que comparten espacios.'),
    ('Triple felina', 'Triple felina', _GATO,
     'Protege contra panleucopenia, rinotraqueítis y calicivirus.'),
    ('Leucemia felina', 'Leucemia', _GATO,
     'Previene la leucemia felina, recomendada para gatos que salen o '
     'conviven con otros gatos.'),
    ('Antirrábica', 'Antirrábica', _GATO,
     'Previene la rabia. Es obligatoria y se refuerza todos los años.'),
]
PERIODICIDAD_DIAS_INICIAL = 365


class VacunaError(Exception):
    """Regla de negocio violada al reservar una vacuna."""


class VacunaNoEncontrada(Exception):
    """La vacuna no existe. La vista la convierte en 404."""


class TurnoVacunaNoEncontrado(Exception):
    """El turno no existe, no es de una mascota del dueño o no es de
    vacunacion. La vista lo convierte en 404."""


# ---------------------------------------------------------------------
# Datos iniciales
# ---------------------------------------------------------------------

@transaction.atomic
def cargar_vacunas_iniciales():
    """Crea las vacunas de VACUNAS_INICIALES que todavia no existen (se
    busca por nombre + especie, asi se puede correr varias veces).
    Devuelve {'creadas': n, 'existentes': n}."""
    resumen = {'creadas': 0, 'existentes': 0}
    for nombre, nombre_corto, especie, descripcion in VACUNAS_INICIALES:
        _, creada = Vacuna.objects.get_or_create(
            nombre=nombre,
            especie=especie,
            defaults={
                'nombre_corto': nombre_corto,
                'descripcion': descripcion,
                'periodicidad_dias': PERIODICIDAD_DIAS_INICIAL,
            },
        )
        resumen['creadas' if creada else 'existentes'] += 1
    return resumen


# ---------------------------------------------------------------------
# Vacunas y horarios
# ---------------------------------------------------------------------

def vacunas_para_mascota(mascota):
    """Vacunas de la especie de la mascota."""
    return list(
        Vacuna.objects.filter(especie=mascota.especie).order_by('nombre')
    )


def obtener_vacuna_para_mascota(mascota, vacuna_id):
    """Devuelve la vacuna si es de la especie de la mascota. Lanza
    VacunaNoEncontrada si no existe y VacunaError si es de otra
    especie."""
    try:
        vacuna = Vacuna.objects.get(pk=vacuna_id)
    except (Vacuna.DoesNotExist, ValueError, TypeError):
        raise VacunaNoEncontrada(vacuna_id)
    if vacuna.especie != mascota.especie:
        raise VacunaError(
            f'La vacuna {vacuna.nombre} es solo para '
            f'{vacuna.get_especie_display().lower()}s: no se puede '
            f'reservar para {mascota.nombre}.'
        )
    return vacuna


def _horarios_de_vacunacion():
    return turnos_disponibles_por_especialidad(
        Veterinario.Especialidad.VACUNACION, DIAS_ADELANTE,
    )


def horarios_libres_vacunacion(limite=10):
    """Proximos horarios libres de veterinarios de VACUNACION, uno por
    fecha y hora (si hay varios veterinarios libres a la misma hora se
    ofrece el primero)."""
    horarios = []
    vistos = set()
    for horario in _horarios_de_vacunacion():
        if horario['fecha_hora'] in vistos:
            continue
        vistos.add(horario['fecha_hora'])
        horarios.append(horario)
        if len(horarios) >= limite:
            break
    return horarios


def obtener_horario_libre(veterinario_id, fecha_hora):
    """Devuelve el horario (dict del service de turnos) si sigue libre
    para ese veterinario de VACUNACION. Si no, lanza VacunaError."""
    try:
        veterinario_id = int(veterinario_id)
        if isinstance(fecha_hora, str):
            fecha_hora = datetime.fromisoformat(fecha_hora)
        if timezone.is_naive(fecha_hora):
            fecha_hora = timezone.make_aware(fecha_hora)
    except (TypeError, ValueError):
        raise VacunaError('El horario elegido no es válido.')

    for horario in _horarios_de_vacunacion():
        if (horario['veterinario_id'] == veterinario_id
                and horario['fecha_hora'] == fecha_hora):
            return horario
    raise VacunaError('Ese horario ya no está disponible. Elegí otro.')


def reservar_turno_vacuna(dueno, mascota_id, vacuna_id, veterinario_id,
                          fecha_hora):
    """Reserva un turno de vacunacion para una mascota del dueño.

    Valida que la mascota sea del dueño y este activa
    (MascotaNoEncontrada), que la vacuna sea de su especie y que el
    horario siga libre con un veterinario de VACUNACION (VacunaError).
    El turno lo crea la funcion de reserva existente
    (crear_turno_manual) y despues se marca con la vacuna.
    """
    mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    vacuna = obtener_vacuna_para_mascota(mascota, vacuna_id)
    horario = obtener_horario_libre(veterinario_id, fecha_hora)

    try:
        with transaction.atomic():
            turno = crear_turno_manual(
                mascota_id=mascota.pk,
                nivel_urgencia_str=NIVEL_URGENCIA_VACUNACION,
                tipo=TIPO_TURNO_VACUNACION,
                veterinario_id=horario['veterinario_id'],
                fecha_hora=horario['fecha_hora'],
            )
            turno.vacuna = vacuna
            turno.save(update_fields=['vacuna'])
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        # crear_turno_manual busca el NivelUrgencia por su nivel.
        raise VacunaError(
            'No se pudo reservar el turno: falta configurar el nivel de '
            f'urgencia {NIVEL_URGENCIA_VACUNACION} en la clínica.'
        )
    return turno


# ---------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------

def _turnos_de_vacunacion():
    return (
        Turno.objects.filter(vacuna__isnull=False)
        .select_related('vacuna', 'mascota', 'veterinario')
    )


def _turnos_del_mes(mascota, anio, mes):
    inicio = timezone.make_aware(datetime(anio, mes, 1))
    fin = timezone.make_aware(
        datetime.combine(_primer_dia_del_mes_siguiente(anio, mes),
                         datetime.min.time())
    )
    return list(
        _turnos_de_vacunacion()
        .filter(mascota=mascota, fecha_hora__gte=inicio, fecha_hora__lt=fin)
        .exclude(estado=Turno.Estado.CANCELADO)
        .order_by('fecha_hora')
    )


def turnos_vacunacion_del_mes(dueno, mascota_id, anio, mes):
    """Turnos de vacunacion reservados (no cancelados) de esa mascota en
    ese mes, ordenados por fecha. Lanza MascotaNoEncontrada si la
    mascota no es del dueño."""
    mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    return _turnos_del_mes(mascota, anio, mes)


def detalle_turno_vacuna(dueno, turno_id):
    """Devuelve el turno si es de una mascota del dueño y tiene vacuna.
    Si no, lanza TurnoVacunaNoEncontrado."""
    try:
        return (
            _turnos_de_vacunacion()
            .prefetch_related('pagos')
            .get(pk=turno_id, mascota__dueno=dueno)
        )
    except (Turno.DoesNotExist, ValueError, TypeError):
        raise TurnoVacunaNoEncontrado(turno_id)


def _primer_dia_del_mes_siguiente(anio, mes):
    return (date(anio, mes, 1) + timedelta(days=32)).replace(day=1)


def interpretar_mes(texto):
    """'2026-10' -> (2026, 10). Si falta o es invalido, el mes actual."""
    try:
        anio, mes = (int(parte) for parte in str(texto).split('-'))
        date(anio, mes, 1)
        if not 2000 <= anio <= 2100:
            raise ValueError(anio)
    except (TypeError, ValueError):
        hoy = timezone.localdate()
        return hoy.year, hoy.month
    return anio, mes


def mes_de_turno(turno):
    """'2026-10': el mes del turno en hora local, para volver al
    calendario en ese mes."""
    return timezone.localtime(turno.fecha_hora).strftime('%Y-%m')


def calendario_vacunacion(dueno, mascota_id, mes_texto=None):
    """Datos para dibujar el almanaque del mes (semanas de domingo a
    sabado) con los turnos de vacunacion de la mascota en cada dia.
    Lanza MascotaNoEncontrada si la mascota no es del dueño."""
    mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    anio, mes = interpretar_mes(mes_texto)
    turnos = _turnos_del_mes(mascota, anio, mes)

    turnos_por_dia = defaultdict(list)
    for turno in turnos:
        turnos_por_dia[timezone.localtime(turno.fecha_hora).date()].append(
            turno
        )

    hoy = timezone.localdate()
    almanaque = calendar.Calendar(firstweekday=calendar.SUNDAY)
    semanas = [
        [
            {
                'fecha': dia,
                'del_mes': dia.month == mes,
                'es_hoy': dia == hoy,
                'turnos': turnos_por_dia.get(dia, []),
            }
            for dia in semana
        ]
        for semana in almanaque.monthdatescalendar(anio, mes)
    ]

    primer_dia = date(anio, mes, 1)
    return {
        'mascota': mascota,
        'primer_dia': primer_dia,
        'semanas': semanas,
        'turnos': turnos,
        'mes_anterior': (primer_dia - timedelta(days=1)).strftime('%Y-%m'),
        'mes_siguiente': _primer_dia_del_mes_siguiente(
            anio, mes,
        ).strftime('%Y-%m'),
    }


# ---------------------------------------------------------------------
# Pendiente (no forma parte de esta etapa): calculo de proximas dosis
# ---------------------------------------------------------------------

def registrar_aplicacion_vacuna(mascota, vacuna, fecha_aplicacion):
    """Registra que una vacuna fue aplicada a una mascota en una
    fecha dada."""
    raise NotImplementedError


def calcular_proxima_dosis(mascota, vacuna):
    """Calcula la fecha de la próxima dosis sumando periodicidad_dias
    a la última aplicación."""
    raise NotImplementedError


def obtener_vacunas_proximas_a_vencer(dias=7):
    """Devuelve las próximas dosis de vacunación que vencen dentro de
    la cantidad de días indicada."""
    raise NotImplementedError
