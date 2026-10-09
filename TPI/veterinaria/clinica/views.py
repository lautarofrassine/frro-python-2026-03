# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from clinica.forms import RegistroForm
from clinica.services.usuarios import (
    RegistroError,
    obtener_dueno_de_usuario,
    registrar_dueno,
)


def registro_view(request):
    if request.user.is_authenticated:
        return redirect('clinica:panel')

    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            try:
                dueno = registrar_dueno(**form.datos_registro())
            except RegistroError as exc:
                form.add_error(exc.campo, str(exc))
            else:
                login(request, dueno.usuario)
                messages.success(
                    request,
                    f'¡Te damos la bienvenida, {dueno.nombre}! Tu cuenta '
                    'fue creada.',
                )
                return redirect('clinica:panel')
    else:
        form = RegistroForm()
    return render(request, 'clinica/registro.html', {'form': form})


@login_required
def panel_view(request):
    dueno = obtener_dueno_de_usuario(request.user)
    return render(request, 'clinica/panel.html', {'dueno': dueno})
