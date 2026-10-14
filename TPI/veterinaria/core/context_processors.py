from core.datos_clinica import CLINICA


def clinica(request):
    """Expone los datos de contacto de la clinica en todas las
    plantillas como `clinica`."""
    return {'clinica': CLINICA}
