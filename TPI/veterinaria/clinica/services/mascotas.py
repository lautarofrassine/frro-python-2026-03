from decimal import Decimal, InvalidOperation

from django.db.models.functions import Lower
from django.utils import timezone

from clinica.models import Mascota

ESPECIES = Mascota.Especie.choices
PESO_MAXIMO_KG = Decimal('120')
CAMPOS_EDITABLES = (
    'nombre', 'especie', 'raza', 'fecha_nacimiento', 'peso_kg',
)


class MascotaError(Exception):
    """Regla de negocio violada al registrar/editar una mascota.
    `campo` indica a que campo del formulario corresponde."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


class MascotaNoEncontrada(Exception):
    """La mascota no existe, no es del dueño o esta dada de baja. La
    vista la convierte en 404 para no revelar que existe."""


def _hoy():
    return timezone.localdate()


def _validar(dueno, nombre, especie, raza, fecha_nacimiento, peso_kg,
             excluir_id=None):
    if dueno is None:
        raise MascotaError(
            'Solo los dueños con cuenta pueden gestionar mascotas.'
        )

    nombre = (nombre or '').strip()
    if not nombre:
        raise MascotaError('Ingresá el nombre de la mascota.', 'nombre')

    especie = str(especie or '').strip().upper()
    if especie not in Mascota.Especie.values:
        raise MascotaError(
            'La clínica solo atiende perros y gatos.', 'especie',
        )

    raza = (raza or '').strip()
    if not raza:
        raise MascotaError(
            'Indicá la raza (si no la sabés, poné "Mestizo").', 'raza',
        )

    if fecha_nacimiento is None:
        raise MascotaError(
            'Ingresá la fecha de nacimiento.', 'fecha_nacimiento',
        )
    if fecha_nacimiento > _hoy():
        raise MascotaError(
            'La fecha de nacimiento no puede ser futura.',
            'fecha_nacimiento',
        )

    try:
        peso_kg = Decimal(str(peso_kg))
    except (InvalidOperation, ValueError):
        raise MascotaError('Ingresá un peso válido.', 'peso_kg')
    if not (0 < peso_kg < PESO_MAXIMO_KG):
        raise MascotaError(
            'El peso tiene que ser mayor a 0 y menor a 120 kg.', 'peso_kg',
        )

    repetida = Mascota.objects.filter(
        dueno=dueno, activo=True, nombre__iexact=nombre,
    )
    if excluir_id is not None:
        repetida = repetida.exclude(pk=excluir_id)
    if repetida.exists():
        raise MascotaError(
            f'Ya tenés una mascota activa llamada {nombre}.', 'nombre',
        )

    return {
        'nombre': nombre,
        'especie': especie,
        'raza': raza,
        'fecha_nacimiento': fecha_nacimiento,
        'peso_kg': peso_kg,
    }


def listar_mascotas(dueno):
    """Mascotas activas del dueño, ordenadas por nombre. El personal de
    la clinica (dueno None) no tiene mascotas."""
    if dueno is None:
        return []
    return list(
        Mascota.objects.filter(dueno=dueno, activo=True)
        .order_by(Lower('nombre'))
    )


def obtener_mascota_de_dueno(dueno, mascota_id):
    """Devuelve la mascota si es del dueño y esta activa. Si no, lanza
    MascotaNoEncontrada."""
    try:
        return Mascota.objects.get(pk=mascota_id, dueno=dueno, activo=True)
    except (Mascota.DoesNotExist, ValueError, TypeError):
        raise MascotaNoEncontrada(mascota_id)


def registrar_mascota(dueno, nombre, especie, raza, fecha_nacimiento,
                      peso_kg):
    """Crea una mascota del dueño. Lanza MascotaError si se viola una
    regla de negocio (especie, fecha, peso o nombre repetido)."""
    datos = _validar(dueno, nombre, especie, raza, fecha_nacimiento, peso_kg)
    return Mascota.objects.create(dueno=dueno, **datos)


def actualizar_mascota(dueno, mascota_id, **datos):
    """Actualiza los campos indicados de una mascota del dueño, con las
    mismas validaciones que el alta (el nombre no choca consigo
    misma)."""
    desconocidos = set(datos) - set(CAMPOS_EDITABLES)
    if desconocidos:
        raise TypeError(f'Campos no editables: {sorted(desconocidos)}')

    mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    actuales = {campo: getattr(mascota, campo) for campo in CAMPOS_EDITABLES}
    actuales.update(datos)
    validados = _validar(dueno, excluir_id=mascota.pk, **actuales)

    for campo, valor in validados.items():
        setattr(mascota, campo, valor)
    mascota.save(update_fields=list(validados))
    return mascota


def dar_de_baja_mascota(dueno, mascota_id):
    """Baja logica: la mascota queda con activo=False y deja de
    listarse, pero conserva su historial."""
    mascota = obtener_mascota_de_dueno(dueno, mascota_id)
    mascota.activo = False
    mascota.save(update_fields=['activo'])
    return mascota


def calcular_edad(mascota):
    """Edad en texto: '3 años', '8 meses', '1 año y 2 meses' o 'Menos de
    1 mes'."""
    hoy = _hoy()
    nacimiento = mascota.fecha_nacimiento
    meses_totales = (
        (hoy.year - nacimiento.year) * 12 + (hoy.month - nacimiento.month)
    )
    if hoy.day < nacimiento.day:
        meses_totales -= 1
    anios, meses = divmod(max(meses_totales, 0), 12)

    texto_anios = f'{anios} año' if anios == 1 else f'{anios} años'
    texto_meses = f'{meses} mes' if meses == 1 else f'{meses} meses'
    if anios and meses:
        return f'{texto_anios} y {texto_meses}'
    if anios:
        return texto_anios
    if meses:
        return texto_meses
    return 'Menos de 1 mes'


def obtener_historial(mascota):
    """Devuelve las entradas de HistorialClinico de una mascota,
    ordenadas por fecha."""
    raise NotImplementedError
