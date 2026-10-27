# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from django.shortcuts import redirect, render

from atencion.services.veterinarios import obtener_veterinario_de_usuario


def inicio_view(request):
    # La landing es para dueños y visitantes; el veterinario va a su
    # agenda (las secciones de la landing son anclas de esta pagina).
    if obtener_veterinario_de_usuario(request.user) is not None:
        return redirect('veterinario:agenda')
    return render(request, 'core/inicio.html')
