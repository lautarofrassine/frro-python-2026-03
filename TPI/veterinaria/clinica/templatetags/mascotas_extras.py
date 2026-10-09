from django import template

from clinica.services.mascotas import calcular_edad

register = template.Library()

ICONOS_ESPECIE = {
    'PERRO': 'fa-dog',
    'GATO': 'fa-cat',
}


@register.filter
def edad(mascota):
    return calcular_edad(mascota)


@register.filter
def icono_especie(especie):
    """Clase de Font Awesome para la especie ('PERRO' -> 'fa-dog')."""
    return ICONOS_ESPECIE.get(str(especie).upper(), 'fa-paw')
