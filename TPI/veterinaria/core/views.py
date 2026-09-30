# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio. Esta
# vista es puramente de presentacion: no hay logica que delegar.
from django.shortcuts import render


def inicio_view(request):
    return render(request, 'core/inicio.html')
