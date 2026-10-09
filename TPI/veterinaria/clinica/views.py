# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from clinica.forms import MascotaForm, RegistroForm
from clinica.services.mascotas import (
    MascotaError,
    MascotaNoEncontrada,
    actualizar_mascota,
    dar_de_baja_mascota,
    listar_mascotas,
    obtener_mascota_de_dueno,
    registrar_mascota,
)
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
    return render(request, 'clinica/panel.html', {
        'dueno': dueno,
        'mascotas': listar_mascotas(dueno),
    })


def dueno_requerido(vista):
    """login_required + pasa el Dueno a la vista. El personal de la
    clinica (sin Dueno) ve un mensaje en lugar de un error."""
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        dueno = obtener_dueno_de_usuario(request.user)
        if dueno is None:
            return render(request, 'clinica/sin_dueno.html')
        return vista(request, dueno, *args, **kwargs)
    return envoltura


def _mascota_o_404(dueno, mascota_id):
    try:
        return obtener_mascota_de_dueno(dueno, mascota_id)
    except MascotaNoEncontrada:
        raise Http404('Mascota no encontrada.')


@dueno_requerido
def mascotas_view(request, dueno):
    return render(request, 'clinica/mascotas_lista.html', {
        'mascotas': listar_mascotas(dueno),
    })


@dueno_requerido
def mascota_nueva_view(request, dueno):
    if request.method == 'POST':
        form = MascotaForm(request.POST)
        if form.is_valid():
            try:
                mascota = registrar_mascota(dueno, **form.datos_mascota())
            except MascotaError as exc:
                form.add_error(exc.campo, str(exc))
            else:
                messages.success(
                    request, f'¡{mascota.nombre} fue registrado/a!',
                )
                return redirect('clinica:mascotas')
    else:
        form = MascotaForm()
    return render(request, 'clinica/mascota_form.html', {
        'form': form,
        'mascota': None,
    })


@dueno_requerido
def mascota_editar_view(request, dueno, mascota_id):
    mascota = _mascota_o_404(dueno, mascota_id)
    if request.method == 'POST':
        form = MascotaForm(request.POST)
        if form.is_valid():
            try:
                mascota = actualizar_mascota(
                    dueno, mascota_id, **form.datos_mascota()
                )
            except MascotaNoEncontrada:
                raise Http404('Mascota no encontrada.')
            except MascotaError as exc:
                form.add_error(exc.campo, str(exc))
            else:
                messages.success(
                    request,
                    f'Los datos de {mascota.nombre} se actualizaron.',
                )
                return redirect('clinica:mascotas')
    else:
        form = MascotaForm.desde_mascota(mascota)
    return render(request, 'clinica/mascota_form.html', {
        'form': form,
        'mascota': mascota,
    })


@dueno_requerido
def mascota_baja_view(request, dueno, mascota_id):
    mascota = _mascota_o_404(dueno, mascota_id)
    if request.method == 'POST':
        try:
            mascota = dar_de_baja_mascota(dueno, mascota_id)
        except MascotaNoEncontrada:
            raise Http404('Mascota no encontrada.')
        messages.success(request, f'{mascota.nombre} fue dado/a de baja.')
        return redirect('clinica:mascotas')
    return render(request, 'clinica/mascota_baja.html', {'mascota': mascota})
