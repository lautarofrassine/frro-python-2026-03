import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_exists(ruta):
    """Indica si un archivo estatico (ej. 'img/hero-perro.jpg') existe,
    para poder mostrar un bloque de reemplazo en vez de una imagen
    rota cuando todavia no fue agregado."""
    return finders.find(ruta) is not None


@register.simple_tag
def static_con_version(ruta):
    """URL del archivo estatico con ?v=<fecha de modificacion>. Cada vez
    que el archivo cambia, cambia la URL y el navegador deja de usar la
    copia vieja que tenia en cache."""
    url = static(ruta)
    archivo = finders.find(ruta)
    if archivo:
        url += f'?v={int(os.path.getmtime(archivo))}'
    return url
