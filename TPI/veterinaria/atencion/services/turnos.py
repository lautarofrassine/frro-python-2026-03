"""Unico lugar con las reglas de los turnos: horarios disponibles,
reserva (con su pago) y cancelacion. El triage, Mis consultas y las
vacunas pasan por aca."""
import warnings
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from administracion.models import Pago
from atencion.models import HorarioAtencion, NivelUrgencia, Turno, Veterinario
from clinica.models import Mascota
from clinica.services.mascotas import (
    MascotaNoEncontrada,
    obtener_mascota_de_dueno,
)

DURACION_TURNO = timedelta(minutes=30)
# Hasta cuantos dias adelante se ofrecen horarios si no se indica.
DIAS_ADELANTE_POR_DEFECTO = 7
# Un turno se puede cancelar con mas de esta anticipacion.
ANTICIPACION_MINIMA_CANCELACION = timedelta(hours=2)

TIPO_CONSULTA = 'Consulta Regular'
TIPO_TRIAGE = 'Triage'
TIPO_VACUNACION = 'Vacunación'

# Precio de la consulta segun la especialidad del veterinario, en pesos.
# Valores ficticios; este es el unico lugar donde se definen.
_E = Veterinario.Especialidad
PRECIO_POR_ESPECIALIDAD = {
    _E.CLINICA_GENERAL: Decimal('15000'),
    _E.CARDIOLOGIA: Decimal('28000'),
    _E.DERMATOLOGIA: Decimal('22000'),
    _E.TRAUMATOLOGIA: Decimal('25000'),
    _E.GASTROENTEROLOGIA: Decimal('24000'),
    _E.OFTALMOLOGIA: Decimal('23000'),
    _E.VACUNACION: Decimal('12000'),
}
# Para veterinarios con una especialidad fuera de la lista.
PRECIO_BASE = PRECIO_POR_ESPECIALIDAD[_E.CLINICA_GENERAL]

# Un turno esta "reservado" mientras esta PENDIENTE o EN_CURSO.
ESTADOS_RESERVADO = (Turno.Estado.PENDIENTE, Turno.Estado.EN_CURSO)


class TurnoError(Exception):
    """Regla de negocio violada al reservar o cancelar un turno. El
    mensaje esta pensado para mostrarselo al dueño."""


class HorarioNoDisponible(TurnoError):
    """El horario ya fue reservado por otra persona."""


class TurnoNoEncontrado(TurnoError):
    """El turno no existe o no es de una mascota del dueño. La vista lo
    convierte en 404 para no revelar que existe."""


# ---------------------------------------------------------------------
# Horarios disponibles
# ---------------------------------------------------------------------

def turnos_disponibles(especialidad=None, veterinario_id=None, desde=None,
                       hasta=None):
    """Horarios libres y futuros de los veterinarios activos, segun su
    HorarioAtencion, del mas cercano al mas lejano.

    Se puede filtrar por especialidad y/o veterinario. `desde` y `hasta`
    acotan el rango (por defecto, desde ahora y por
    DIAS_ADELANTE_POR_DEFECTO dias).

    Devuelve una lista de dicts con 'fecha_hora', 'veterinario_id' y
    'veterinario_nombre'.
    """
    ahora = timezone.now()
    desde = max(desde or ahora, ahora)
    hasta = hasta or desde + timedelta(days=DIAS_ADELANTE_POR_DEFECTO)

    horarios = HorarioAtencion.objects.filter(
        veterinario__estado=Veterinario.Estado.ACTIVO,
    ).select_related('veterinario')
    if especialidad:
        horarios = horarios.filter(veterinario__especialidad=especialidad)
    if veterinario_id:
        horarios = horarios.filter(veterinario_id=veterinario_id)
    horarios_por_dia = defaultdict(list)
    for horario in horarios:
        horarios_por_dia[horario.dia_semana].append(horario)

    # Una sola consulta para los ocupados del rango (la base esta en la
    # nube); los cancelados dejan libre el horario.
    ocupados = set(
        Turno.objects.filter(fecha_hora__gt=desde, fecha_hora__lte=hasta)
        .exclude(estado=Turno.Estado.CANCELADO)
        .values_list('veterinario_id', 'fecha_hora')
    )

    disponibles = []
    dia = timezone.localtime(desde).date()
    ultimo_dia = timezone.localtime(hasta).date()
    while dia <= ultimo_dia:
        for horario in horarios_por_dia[dia.weekday()]:
            inicio = timezone.make_aware(
                datetime.combine(dia, horario.hora_inicio)
            )
            fin = timezone.make_aware(datetime.combine(dia, horario.hora_fin))
            while inicio + DURACION_TURNO <= fin:
                libre = (horario.veterinario_id, inicio) not in ocupados
                if desde < inicio <= hasta and libre:
                    disponibles.append({
                        'fecha_hora': inicio,
                        'veterinario_id': horario.veterinario_id,
                        'veterinario_nombre': horario.veterinario.nombre,
                    })
                inicio += DURACION_TURNO
        dia += timedelta(days=1)

    disponibles.sort(
        key=lambda h: (h['fecha_hora'], h['veterinario_nombre'])
    )
    return disponibles


def _dentro_del_horario_de_atencion(veterinario, fecha_hora):
    """True si fecha_hora es el comienzo de un turno de 30 minutos
    dentro de un HorarioAtencion del veterinario."""
    local = timezone.localtime(fecha_hora)
    if local.second or local.microsecond:
        return False
    for horario in veterinario.horarios_atencion.filter(
        dia_semana=local.weekday(),
    ):
        inicio = datetime.combine(local.date(), horario.hora_inicio)
        fin = datetime.combine(local.date(), horario.hora_fin)
        comienzo = local.replace(tzinfo=None)
        if (inicio <= comienzo
                and comienzo + DURACION_TURNO <= fin
                and (comienzo - inicio) % DURACION_TURNO == timedelta(0)):
            return True
    return False


# ---------------------------------------------------------------------
# Reserva
# ---------------------------------------------------------------------

def _interpretar_fecha_hora(fecha_hora):
    try:
        if isinstance(fecha_hora, str):
            fecha_hora = datetime.fromisoformat(fecha_hora)
        if timezone.is_naive(fecha_hora):
            fecha_hora = timezone.make_aware(fecha_hora)
    except (TypeError, ValueError, AttributeError):
        raise TurnoError('El horario elegido no es válido.')
    return fecha_hora


def _obtener_nivel_urgencia(nivel):
    """Acepta un NivelUrgencia, su codigo ('ALTA') o None (BAJA: una
    consulta programada no es una urgencia). El turno lo exige, asi que
    si la fila no existe se crea."""
    if isinstance(nivel, NivelUrgencia):
        return nivel
    nivel = nivel or NivelUrgencia.Nivel.BAJA
    if nivel not in NivelUrgencia.Nivel.values:
        raise TurnoError('El nivel de urgencia no es válido.')
    existente = (
        NivelUrgencia.objects.filter(nivel_urgencia=nivel)
        .order_by('id')
        .first()
    )
    return existente or NivelUrgencia.objects.create(
        nivel_urgencia=nivel, sintomas_descripcion='',
    )


def precio_de_turno(veterinario):
    return PRECIO_POR_ESPECIALIDAD.get(veterinario.especialidad, PRECIO_BASE)


def reservar_turno(dueno, mascota_id, veterinario_id, fecha_hora,
                   nivel_urgencia=None, vacuna=None, motivo='', tipo=None):
    """Reserva un turno para una mascota del dueño y crea su Pago
    PENDIENTE con el precio de la especialidad. Todo o nada.

    Valida que la mascota sea del dueño y este activa, que el
    veterinario este activo, que el horario sea futuro, este dentro de
    su HorarioAtencion y siga libre. Ante cualquier regla violada lanza
    TurnoError (HorarioNoDisponible si el horario ya fue reservado).

    `fecha_hora` puede ser un datetime o un texto ISO. `nivel_urgencia`
    es opcional (BAJA). `vacuna` marca el turno como de vacunacion.
    """
    try:
        mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    except MascotaNoEncontrada:
        raise TurnoError(
            'La mascota elegida no existe o no está entre tus mascotas.'
        )
    fecha_hora = _interpretar_fecha_hora(fecha_hora)
    if fecha_hora <= timezone.now():
        raise TurnoError('No se puede reservar un turno en un horario pasado.')
    if tipo is None:
        tipo = TIPO_VACUNACION if vacuna else TIPO_CONSULTA

    try:
        with transaction.atomic():
            # Bloquea al veterinario: dos reservas simultaneas para el
            # mismo veterinario se atienden de a una.
            try:
                veterinario = Veterinario.objects.select_for_update().get(
                    pk=veterinario_id, estado=Veterinario.Estado.ACTIVO,
                )
            except (Veterinario.DoesNotExist, ValueError, TypeError):
                raise TurnoError('El veterinario elegido no está disponible.')
            if not _dentro_del_horario_de_atencion(veterinario, fecha_hora):
                raise TurnoError(
                    f'{veterinario.nombre} no atiende en ese horario.'
                )
            ocupado = (
                Turno.objects.filter(
                    veterinario=veterinario, fecha_hora=fecha_hora,
                )
                .exclude(estado=Turno.Estado.CANCELADO)
                .exists()
            )
            if ocupado:
                raise HorarioNoDisponible(
                    'Este turno acaba de ser reservado, elegí otro horario.'
                )

            turno = Turno.objects.create(
                mascota=mascota,
                veterinario=veterinario,
                nivel_urgencia=_obtener_nivel_urgencia(nivel_urgencia),
                vacuna=vacuna,
                fecha_hora=fecha_hora,
                tipo=tipo,
                motivo=motivo or '',
                estado=Turno.Estado.PENDIENTE,
            )
            Pago.objects.create(
                turno=turno,
                monto_total=precio_de_turno(veterinario),
                estado=Pago.Estado.PENDIENTE,
            )
    except IntegrityError:
        # Respaldo: la restriccion de unicidad de la base rechazo una
        # reserva simultanea que paso las verificaciones.
        raise HorarioNoDisponible(
            'Este turno acaba de ser reservado, elegí otro horario.'
        )
    return turno


def asignar_turno_automatico(dueno, mascota_id, nivel_urgencia,
                             tipo=TIPO_TRIAGE):
    """Reserva el horario libre mas proximo (triage CRITICA). Si justo
    lo ocupan, prueba con los siguientes. Lanza TurnoError si no hay
    veterinarios disponibles."""
    for horario in turnos_disponibles()[:5]:
        try:
            return reservar_turno(
                dueno,
                mascota_id,
                horario['veterinario_id'],
                horario['fecha_hora'],
                nivel_urgencia=nivel_urgencia,
                tipo=tipo,
            )
        except HorarioNoDisponible:
            continue
    raise TurnoError(
        'No hay veterinarios disponibles para atender la urgencia.'
    )


# ---------------------------------------------------------------------
# Turnos del dueño y cancelacion
# ---------------------------------------------------------------------

def _turnos_de_dueno(dueno):
    # select_related/prefetch_related: una consulta para los turnos y
    # otra para sus pagos, en vez de una por turno (la base esta en la
    # nube).
    return (
        Turno.objects.filter(mascota__dueno=dueno)
        .select_related('mascota', 'veterinario', 'vacuna')
        .prefetch_related('pagos')
    )


def proximos_turnos(dueno):
    """Turnos futuros reservados (PENDIENTE o EN_CURSO) de las mascotas
    activas del dueño, del mas cercano al mas lejano. El personal de la
    clinica (dueno None) no tiene turnos."""
    if dueno is None:
        return []
    return list(
        _turnos_de_dueno(dueno)
        .filter(
            mascota__activo=True,
            fecha_hora__gte=timezone.now(),
            estado__in=ESTADOS_RESERVADO,
        )
        .order_by('fecha_hora')
    )


def historial_turnos(dueno, limite=10):
    """Los ultimos `limite` turnos del dueño que ya no son proximos: los
    que ya pasaron y los finalizados o cancelados, del mas reciente al
    mas viejo. Incluye los de mascotas dadas de baja."""
    if dueno is None:
        return []
    return list(
        _turnos_de_dueno(dueno)
        .exclude(
            fecha_hora__gte=timezone.now(),
            estado__in=ESTADOS_RESERVADO,
        )
        .order_by('-fecha_hora')[:limite]
    )


def obtener_turno_de_dueno(dueno, turno_id):
    """Devuelve el turno si es de una mascota del dueño. Si no, lanza
    TurnoNoEncontrado."""
    try:
        return _turnos_de_dueno(dueno).get(pk=turno_id)
    except (Turno.DoesNotExist, ValueError, TypeError):
        raise TurnoNoEncontrado('El turno no existe.')


def _motivo_para_no_cancelar(turno):
    if turno.estado != Turno.Estado.PENDIENTE:
        return 'Solo se pueden cancelar turnos pendientes.'
    faltan = turno.fecha_hora - timezone.now()
    if faltan <= timedelta(0):
        return 'Este turno ya pasó.'
    if faltan <= ANTICIPACION_MINIMA_CANCELACION:
        return 'Los turnos se pueden cancelar hasta 2 horas antes.'
    return None


def puede_cancelarse(turno):
    """True si el dueño todavia puede cancelar el turno (pendiente y
    con mas de 2 horas de anticipacion)."""
    return _motivo_para_no_cancelar(turno) is None


def cancelar_turno(dueno, turno_id):
    """Cancela un turno futuro del dueño con mas de 2 horas de
    anticipacion: el turno pasa a CANCELADO (su horario queda libre) y
    su pago pendiente a CANCELADO. Lanza TurnoNoEncontrado si no es del
    dueño y TurnoError si ya no se puede cancelar."""
    with transaction.atomic():
        try:
            turno = (
                Turno.objects.select_for_update()
                .select_related('mascota', 'veterinario')
                .get(pk=turno_id, mascota__dueno=dueno)
            )
        except (Turno.DoesNotExist, ValueError, TypeError):
            raise TurnoNoEncontrado('El turno no existe.')
        motivo = _motivo_para_no_cancelar(turno)
        if motivo:
            raise TurnoError(motivo)

        turno.estado = Turno.Estado.CANCELADO
        turno.save(update_fields=['estado'])
        turno.pagos.filter(estado=Pago.Estado.PENDIENTE).update(
            estado=Pago.Estado.CANCELADO,
        )
    return turno


# ---------------------------------------------------------------------
# Obsoleto: se mantiene para no romper llamadas existentes
# ---------------------------------------------------------------------

def obtener_turnos_disponibles(dias_adelante=DIAS_ADELANTE_POR_DEFECTO):
    """Obsoleto: usar turnos_disponibles()."""
    warnings.warn(
        'obtener_turnos_disponibles esta obsoleto; usar turnos_disponibles.',
        DeprecationWarning,
        stacklevel=2,
    )
    return turnos_disponibles(
        hasta=timezone.now() + timedelta(days=dias_adelante),
    )


def crear_turno_manual(mascota_id, nivel_urgencia_str, tipo, veterinario_id,
                       fecha_hora):
    """Obsoleto: usar reservar_turno(dueno, ...), que ademas valida que
    la mascota sea de quien reserva. Este alias no recibe al dueño, asi
    que usa al de la mascota; el resto de las validaciones y el pago son
    los de reservar_turno."""
    warnings.warn(
        'crear_turno_manual esta obsoleto; usar reservar_turno.',
        DeprecationWarning,
        stacklevel=2,
    )
    mascota = (
        Mascota.objects.select_related('dueno').filter(pk=mascota_id).first()
    )
    if mascota is None:
        raise TurnoError('La mascota elegida no existe.')
    return reservar_turno(
        mascota.dueno,
        mascota_id,
        veterinario_id,
        fecha_hora,
        nivel_urgencia=nivel_urgencia_str,
        tipo=tipo,
    )
