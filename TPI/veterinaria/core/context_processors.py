from django.utils.functional import SimpleLazyObject

from atencion.services.veterinarios import obtener_veterinario_de_usuario
from core.datos_clinica import CLINICA


def clinica(request):
    """Expone los datos de contacto de la clinica en todas las
    plantillas como `clinica`, y `veterinario_actual` (el Veterinario
    del usuario logueado o None) para armar el menu segun el rol. Se
    consulta solo si una plantilla lo usa."""
    return {
        'clinica': CLINICA,
        'veterinario_actual': SimpleLazyObject(
            lambda: obtener_veterinario_de_usuario(request.user)
        ),
    }
