"""Historias clinicas vistas por los veterinarios. Un veterinario solo
accede a las mascotas que atendio o tiene en agenda (al menos un turno
con el), pero ve las entradas que cargaron todos los veterinarios."""
from django.db.models import Q
from django.db.models.functions import Lower

from atencion.models import Turno
from clinica.models import HistorialClinico, Mascota
from clinica.services.mascotas import MascotaNoEncontrada


class HistoriaError(Exception):
    """Dato invalido al cargar o editar una entrada. `campo` indica a
    que campo del formulario corresponde."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


class EntradaNoEncontrada(Exception):
    """La entrada no existe o es de una mascota a la que el veterinario
    no tiene acceso. La vista responde 404."""


class EntradaAjena(Exception):
    """La entrada la cargo otro veterinario: no se puede editar. La
    vista responde 403."""


def _mascotas_del_veterinario(veterinario):
    return Mascota.objects.filter(turnos__veterinario=veterinario).distinct()


def mascotas_atendidas(veterinario, buscar=''):
    """Mascotas que el veterinario atendio o tiene en agenda, con su
    dueño, filtradas por nombre de mascota o de dueño."""
    mascotas = _mascotas_del_veterinario(veterinario).select_related('dueno')
    buscar = (buscar or '').strip()
    if buscar:
        mascotas = mascotas.filter(
            Q(nombre__icontains=buscar)
            | Q(dueno__nombre__icontains=buscar)
            | Q(dueno__apellido__icontains=buscar)
        )
    return list(mascotas.order_by(Lower('nombre')))


def obtener_mascota_atendida(veterinario, mascota_id):
    """La mascota si el veterinario la atendio o la tiene en agenda. Si
    no, lanza MascotaNoEncontrada (la vista responde 404)."""
    try:
        return (
            _mascotas_del_veterinario(veterinario)
            .select_related('dueno')
            .get(pk=mascota_id)
        )
    except (Mascota.DoesNotExist, ValueError, TypeError):
        raise MascotaNoEncontrada(mascota_id)


def historia_clinica(mascota):
    """Todas las entradas de la mascota, de la mas reciente a la mas
    vieja, con el veterinario que las cargo."""
    return list(
        mascota.historial_clinico
        .select_related('veterinario', 'turno')
        .order_by('-fecha', '-id')
    )


def _validar(diagnostico, tratamiento, observaciones):
    diagnostico = (diagnostico or '').strip()
    tratamiento = (tratamiento or '').strip()
    if not diagnostico:
        raise HistoriaError('Escribí el diagnóstico.', 'diagnostico')
    if not tratamiento:
        raise HistoriaError('Escribí el tratamiento.', 'tratamiento')
    return {
        'diagnostico': diagnostico,
        'tratamiento': tratamiento,
        'observaciones': (observaciones or '').strip(),
    }


def obtener_turno_para_entrada(veterinario, mascota, turno_id):
    """El turno al que se asocia la entrada: tiene que ser de este
    veterinario y de esta mascota. Lanza HistoriaError si no."""
    if not turno_id:
        return None
    try:
        turno = Turno.objects.filter(
            pk=turno_id, veterinario=veterinario, mascota=mascota,
        ).first()
    except (ValueError, TypeError):
        turno = None
    if turno is None:
        raise HistoriaError(
            'El turno indicado no es tuyo o no es de esta mascota.'
        )
    return turno


def cargar_entrada(veterinario, mascota_id, diagnostico, tratamiento,
                   observaciones='', turno_id=None):
    """Agrega una entrada a la historia clinica, a nombre del
    veterinario y, si viene, asociada al turno. Lanza
    MascotaNoEncontrada o HistoriaError."""
    mascota = obtener_mascota_atendida(veterinario, mascota_id)
    turno = obtener_turno_para_entrada(veterinario, mascota, turno_id)
    datos = _validar(diagnostico, tratamiento, observaciones)
    return HistorialClinico.objects.create(
        mascota=mascota, veterinario=veterinario, turno=turno, **datos,
    )


def obtener_entrada_propia(veterinario, entrada_id):
    """La entrada si el veterinario la cargo. Lanza EntradaNoEncontrada
    si no existe o no tiene acceso a la mascota, y EntradaAjena si la
    cargo otro veterinario."""
    try:
        entrada = (
            HistorialClinico.objects.select_related('mascota', 'turno')
            .filter(
                pk=entrada_id,
                mascota__in=_mascotas_del_veterinario(veterinario),
            )
            .first()
        )
    except (ValueError, TypeError):
        entrada = None
    if entrada is None:
        raise EntradaNoEncontrada(entrada_id)
    if entrada.veterinario_id != veterinario.pk:
        raise EntradaAjena(entrada_id)
    return entrada


def editar_entrada(veterinario, entrada_id, diagnostico, tratamiento,
                   observaciones=''):
    """Modifica una entrada propia (las de otros veterinarios no)."""
    entrada = obtener_entrada_propia(veterinario, entrada_id)
    for campo, valor in _validar(
        diagnostico, tratamiento, observaciones,
    ).items():
        setattr(entrada, campo, valor)
    entrada.save(update_fields=['diagnostico', 'tratamiento', 'observaciones'])
    return entrada
