"""Obras sociales: vienen precargadas; los dueños eligen una (o
ninguna) y los veterinarios eligen las que atienden. Solo se pueden
elegir las activas."""
from decimal import Decimal

from django.db import transaction

from administracion.models import ObraSocial
from atencion.models import Veterinario

# Datos ficticios (no son marcas reales).
OBRAS_SOCIALES_INICIALES = [
    {
        'nombre': 'VetSalud Plus',
        'porcentaje_cobertura': Decimal('70'),
        'tope_mensual': Decimal('50000'),
        'cubre_consultas': True,
        'cubre_vacunacion': True,
        'cubre_guardia': True,
    },
    {
        'nombre': 'Mascotas Protegidas',
        'porcentaje_cobertura': Decimal('50'),
        'tope_mensual': Decimal('20000'),
        'cubre_consultas': True,
        'cubre_vacunacion': True,
        'cubre_guardia': False,
    },
    {
        'nombre': 'PetCare Básico',
        'porcentaje_cobertura': Decimal('30'),
        'tope_mensual': Decimal('10000'),
        'cubre_consultas': False,
        'cubre_vacunacion': True,
        'cubre_guardia': False,
    },
    {
        'nombre': 'Huellitas Total',
        'porcentaje_cobertura': Decimal('100'),
        'tope_mensual': Decimal('80000'),
        'cubre_consultas': True,
        'cubre_vacunacion': True,
        'cubre_guardia': True,
    },
]


class ObraSocialError(Exception):
    """Eleccion de obra social invalida. `campo` indica a que campo del
    formulario corresponde."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


def listar_obras_sociales_activas():
    """Obras sociales que se pueden elegir, por nombre."""
    return list(ObraSocial.objects.filter(activa=True).order_by('nombre'))


def _obra_social_activa(obra_social_id):
    try:
        return ObraSocial.objects.filter(
            pk=obra_social_id, activa=True,
        ).first()
    except (ValueError, TypeError):
        return None


def asignar_obra_social_a_dueno(dueno, obra_social_id, numero_afiliado=''):
    """Elige la obra social del dueño, o ninguna (obra_social_id vacio o
    None, y entonces se limpia el numero de afiliado). Con obra social,
    el numero de afiliado es obligatorio. Lanza ObraSocialError."""
    numero_afiliado = (numero_afiliado or '').strip()
    if obra_social_id in (None, ''):
        obra_social = None
        numero_afiliado = ''
    else:
        obra_social = _obra_social_activa(obra_social_id)
        if obra_social is None:
            raise ObraSocialError(
                'La obra social elegida no está disponible.', 'obra_social',
            )
        if not numero_afiliado:
            raise ObraSocialError(
                'Ingresá tu número de afiliado.', 'numero_afiliado',
            )
    dueno.obra_social = obra_social
    dueno.numero_afiliado = numero_afiliado
    dueno.save(update_fields=['obra_social', 'numero_afiliado'])
    return dueno


def obras_sociales_de_veterinario(veterinario):
    """Obras sociales que atiende el veterinario, por nombre."""
    return list(veterinario.obras_sociales.order_by('nombre'))


def actualizar_obras_sociales_de_veterinario(veterinario, obras_sociales_ids):
    """Reemplaza las obras sociales que atiende el veterinario. Todas
    tienen que existir y estar activas; si no, lanza ObraSocialError y
    no cambia nada."""
    try:
        ids = {int(obra_social_id) for obra_social_id in obras_sociales_ids}
    except (ValueError, TypeError):
        raise ObraSocialError('Alguna de las obras sociales no es válida.')
    elegidas = list(ObraSocial.objects.filter(pk__in=ids, activa=True))
    if len(elegidas) != len(ids):
        raise ObraSocialError(
            'Alguna de las obras sociales elegidas no existe o no está '
            'activa.'
        )
    veterinario.obras_sociales.set(elegidas)
    return obras_sociales_de_veterinario(veterinario)


# ---------------------------------------------------------------------
# Datos iniciales
# ---------------------------------------------------------------------

@transaction.atomic
def cargar_obras_sociales_iniciales():
    """Crea las obras sociales de OBRAS_SOCIALES_INICIALES que todavia no
    existen (se busca por nombre) y a las que ya existen les actualiza
    cobertura, tope y servicios con los de la lista (no toca `activa`).
    Devuelve {'creadas', 'existentes'}."""
    resumen = {'creadas': 0, 'existentes': 0}
    for datos in OBRAS_SOCIALES_INICIALES:
        datos = dict(datos)
        _, creada = ObraSocial.objects.update_or_create(
            nombre=datos.pop('nombre'), defaults=datos,
        )
        resumen['creadas' if creada else 'existentes'] += 1
    return resumen


@transaction.atomic
def asignar_obras_sociales_de_prueba():
    """Para tener datos de prueba: a cada veterinario activo que todavia
    no atiende ninguna obra social le asigna entre 1 y 3 activas. Es
    deterministico (depende del orden por matricula) y no pisa lo que
    cada veterinario ya eligio. Devuelve cuantos veterinarios cambio."""
    obras = list(ObraSocial.objects.filter(activa=True).order_by('nombre'))
    if not obras:
        return 0
    cambiados = 0
    veterinarios = Veterinario.objects.filter(
        estado=Veterinario.Estado.ACTIVO,
    ).order_by('matricula')
    for posicion, veterinario in enumerate(veterinarios):
        if veterinario.obras_sociales.exists():
            continue
        cantidad = min(1 + posicion % 3, len(obras))
        veterinario.obras_sociales.set([
            obras[(posicion + desplazamiento) % len(obras)]
            for desplazamiento in range(cantidad)
        ])
        cambiados += 1
    return cambiados
