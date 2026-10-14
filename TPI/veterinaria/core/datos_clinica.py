"""Datos de contacto de la clinica, en un solo lugar. Las plantillas
los reciben como `clinica` (ver core/context_processors.py)."""
from urllib.parse import quote_plus

_DIRECCION = 'Av. Pellegrini 1250, Rosario, Santa Fe'

# Datos ficticios.
CLINICA = {
    'nombre': 'ClinicaVet24',
    'direccion': _DIRECCION,
    'telefono': '(0341) 555-0000',
    # Para los links tel: (formato internacional, sin espacios).
    'telefono_link': '+543415550000',
    'horario': 'Atención las 24 hs, todos los días',
    'maps_url': (
        'https://www.google.com/maps/search/?api=1&query='
        + quote_plus(_DIRECCION)
    ),
}
