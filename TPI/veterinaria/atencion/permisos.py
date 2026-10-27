"""Decoradores de acceso por rol para las vistas. Un dueño no entra a
las pantallas de veterinario ni un veterinario a las de dueño (403)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from atencion.services.veterinarios import obtener_veterinario_de_usuario


def veterinario_requerido(vista):
    """login_required + solo veterinarios (los demas reciben 403). Pasa
    el Veterinario a la vista."""
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        veterinario = obtener_veterinario_de_usuario(request.user)
        if veterinario is None:
            raise PermissionDenied('Sección solo para veterinarios.')
        return vista(request, veterinario, *args, **kwargs)
    return envoltura


def rechazar_veterinarios(request):
    """Lanza PermissionDenied (403) si quien navega es un veterinario."""
    if obtener_veterinario_de_usuario(request.user) is not None:
        raise PermissionDenied('Sección solo para dueños.')


def solo_duenos(vista):
    """login_required + los veterinarios reciben 403."""
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        rechazar_veterinarios(request)
        return vista(request, *args, **kwargs)
    return envoltura
