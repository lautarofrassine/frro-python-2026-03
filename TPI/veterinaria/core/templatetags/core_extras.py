from django import template
from django.contrib.staticfiles import finders

register = template.Library()


@register.simple_tag
def static_exists(ruta):
    """Indica si un archivo estatico (ej. 'img/hero-perro.jpg') existe,
    para poder mostrar un bloque de reemplazo en vez de una imagen
    rota cuando todavia no fue agregado."""
    return finders.find(ruta) is not None
