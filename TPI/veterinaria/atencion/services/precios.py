"""Precios por atencion de los veterinarios.

Cada veterinario tiene su historial de precios (PrecioVeterinario). El
precio de un turno es el vigente en la fecha del turno; si el
veterinario no tiene ninguno, se usa el de su especialidad. Los cambios
se programan con al menos 14 dias de anticipacion y solo se pueden
eliminar mientras todavia no rigen.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from atencion.models import PrecioVeterinario, Veterinario

# Precio de la consulta segun la especialidad del veterinario, en pesos.
# Valores ficticios. Solo se usan como precio inicial (y si un
# veterinario no tiene ningun precio cargado).
_E = Veterinario.Especialidad
PRECIO_POR_ESPECIALIDAD = {
    _E.CLINICA_GENERAL: Decimal('15000'),
    _E.CARDIOLOGIA: Decimal('28000'),
    _E.DERMATOLOGIA: Decimal('22000'),
    _E.TRAUMATOLOGIA: Decimal('25000'),
    _E.GASTROENTEROLOGIA: Decimal('24000'),
    _E.OFTALMOLOGIA: Decimal('23000'),
    _E.VACUNACION: Decimal('12000'),
    _E.GUARDIA: Decimal('30000'),
}
# Para veterinarios con una especialidad fuera de la lista.
PRECIO_BASE = PRECIO_POR_ESPECIALIDAD[_E.CLINICA_GENERAL]

# Un cambio de precio rige como minimo esta cantidad de dias despues.
DIAS_MINIMOS_PARA_CAMBIO = 14


class PrecioError(Exception):
    """Regla de precios violada. `campo` indica a que campo del
    formulario corresponde."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


def precio_de_especialidad(especialidad):
    return PRECIO_POR_ESPECIALIDAD.get(especialidad, PRECIO_BASE)


def _como_fecha(fecha):
    if isinstance(fecha, datetime):
        if timezone.is_aware(fecha):
            fecha = timezone.localtime(fecha)
        return fecha.date()
    return fecha


def precio_vigente(veterinario, fecha=None):
    """Monto vigente del veterinario en `fecha` (date o datetime; por
    defecto hoy): el de fecha de vigencia mas reciente que sea menor o
    igual. Sin ninguno, el de su especialidad."""
    fecha = _como_fecha(fecha) if fecha else timezone.localdate()
    precio = (
        PrecioVeterinario.objects
        .filter(veterinario=veterinario, vigente_desde__lte=fecha)
        .order_by('-vigente_desde')
        .first()
    )
    if precio is None:
        return precio_de_especialidad(veterinario.especialidad)
    return precio.monto


def fecha_minima_de_cambio():
    """Primera fecha desde la que puede regir un cambio cargado hoy."""
    return timezone.localdate() + timedelta(days=DIAS_MINIMOS_PARA_CAMBIO)


def programar_cambio_de_precio(veterinario, monto, vigente_desde):
    """Programa un nuevo precio del veterinario. El monto tiene que ser
    mayor a cero y la fecha, al menos 14 dias posterior a hoy y sin otro
    cambio en esa misma fecha. Lanza PrecioError."""
    try:
        monto = Decimal(str(monto))
    except (InvalidOperation, TypeError, ValueError):
        raise PrecioError('Ingresá un monto válido.', 'monto')
    if not monto.is_finite() or monto <= 0:
        raise PrecioError('El precio tiene que ser mayor a cero.', 'monto')
    if isinstance(vigente_desde, str):
        try:
            vigente_desde = date.fromisoformat(vigente_desde)
        except ValueError:
            vigente_desde = None
    if not isinstance(vigente_desde, date):
        raise PrecioError('Ingresá una fecha válida.', 'vigente_desde')
    vigente_desde = _como_fecha(vigente_desde)
    minima = fecha_minima_de_cambio()
    if vigente_desde < minima:
        raise PrecioError(
            f'El nuevo precio debe regir desde el {minima:%d/%m/%Y} o '
            'después.',
            'vigente_desde',
        )
    repetida = PrecioError(
        f'Ya tenés un cambio de precio desde el {vigente_desde:%d/%m/%Y}. '
        'Eliminalo si querés cambiarlo.',
        'vigente_desde',
    )
    if veterinario.precios.filter(vigente_desde=vigente_desde).exists():
        raise repetida
    try:
        with transaction.atomic():
            return PrecioVeterinario.objects.create(
                veterinario=veterinario, monto=monto,
                vigente_desde=vigente_desde,
            )
    except IntegrityError:
        # Respaldo ante dos cargas simultaneas con la misma fecha.
        raise repetida


def eliminar_cambio_de_precio(veterinario, precio_id):
    """Elimina un cambio de precio propio que todavia no rige. Lanza
    PrecioError si no es suyo o si ya rige (o rigio)."""
    try:
        precio = veterinario.precios.filter(pk=precio_id).first()
    except (ValueError, TypeError):
        precio = None
    if precio is None:
        raise PrecioError('No encontramos ese cambio de precio.')
    if precio.vigente_desde <= timezone.localdate():
        raise PrecioError(
            'Solo se pueden eliminar los cambios de precio que todavía no '
            'rigen.'
        )
    precio.delete()


def historial_de_precios(veterinario):
    """Para "Mis precios": el monto vigente hoy (con su registro, o None
    si sale de la especialidad), los cambios programados (del mas
    proximo al mas lejano) y los anteriores (del mas reciente al mas
    viejo)."""
    hoy = timezone.localdate()
    precios = list(veterinario.precios.order_by('-vigente_desde'))
    programados = [p for p in precios if p.vigente_desde > hoy]
    pasados = [p for p in precios if p.vigente_desde <= hoy]
    vigente = pasados[0] if pasados else None
    return {
        'vigente': vigente,
        'monto_vigente': (
            vigente.monto if vigente
            else precio_de_especialidad(veterinario.especialidad)
        ),
        'programados': list(reversed(programados)),
        'anteriores': pasados[1:],
    }


# ---------------------------------------------------------------------
# Datos iniciales
# ---------------------------------------------------------------------

# Desde cuando rige el precio inicial de cada veterinario.
VIGENCIA_PRECIO_INICIAL = date(2026, 1, 1)


@transaction.atomic
def cargar_precios_iniciales():
    """A cada veterinario sin ningun precio le crea uno con el de su
    especialidad, vigente desde VIGENCIA_PRECIO_INICIAL. Se puede correr
    varias veces. Devuelve cuantos precios creo."""
    nuevos = [
        PrecioVeterinario(
            veterinario=veterinario,
            monto=precio_de_especialidad(veterinario.especialidad),
            vigente_desde=VIGENCIA_PRECIO_INICIAL,
        )
        for veterinario in Veterinario.objects.filter(precios__isnull=True)
    ]
    PrecioVeterinario.objects.bulk_create(nuevos)
    return len(nuevos)
