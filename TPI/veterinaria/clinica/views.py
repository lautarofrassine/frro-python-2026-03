# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from atencion.permisos import rechazar_veterinarios
from atencion.services.veterinarios import obtener_veterinario_de_usuario
from clinica.forms import LoginForm, MascotaForm, RegistroForm
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
from clinica.services.vacunas import (
    TurnoVacunaNoEncontrado,
    VacunaError,
    VacunaNoEncontrada,
    calendario_vacunacion,
    detalle_turno_vacuna,
    horarios_libres_vacunacion,
    mes_de_turno,
    obtener_horario_libre,
    obtener_vacuna_para_mascota,
    reservar_turno_vacuna,
    vacunas_para_mascota,
)


def registro_view(request):
    if request.user.is_authenticated:
        return redirect('clinica:panel')

    # A donde ir despues de registrarse (solo direcciones del sitio).
    siguiente = request.POST.get('next') or request.GET.get('next') or ''
    if not url_has_allowed_host_and_scheme(
        siguiente, allowed_hosts={request.get_host()},
    ):
        siguiente = ''

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
                return redirect(siguiente or 'clinica:panel')
    else:
        form = RegistroForm()
    return render(request, 'clinica/registro.html', {
        'form': form,
        'next': siguiente,
    })


# Todas las pantallas de veterinario cuelgan de aca.
PREFIJO_VETERINARIO = '/veterinario/'


class IngresarView(auth_views.LoginView):
    """Misma pantalla para dueños y veterinarios. Despues de ingresar,
    cada uno va a su inicio: el dueño a su panel y el veterinario a su
    agenda. El `next` se respeta solo si corresponde al rol."""

    template_name = 'clinica/ingresar.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        es_veterinario = (
            obtener_veterinario_de_usuario(self.request.user) is not None
        )
        siguiente = self.get_redirect_url()
        if siguiente and (
            siguiente.startswith(PREFIJO_VETERINARIO) == es_veterinario
        ):
            return siguiente
        if es_veterinario:
            return reverse('veterinario:agenda')
        return reverse('clinica:panel')


@login_required
def panel_view(request):
    if obtener_veterinario_de_usuario(request.user) is not None:
        return redirect('veterinario:agenda')
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
        # Los veterinarios no tienen acceso a las pantallas de dueño.
        rechazar_veterinarios(request)
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


def _url_con_parametros(nombre, **parametros):
    return f'{reverse(nombre)}?{urlencode(parametros)}'


@dueno_requerido
def vacunas_view(request, dueno):
    mascotas = listar_mascotas(dueno)
    if not mascotas:
        return render(request, 'clinica/vacunas.html', {'mascotas': []})

    # Por defecto, la primera mascota del dueño.
    mascota_id = request.GET.get('mascota') or mascotas[0].pk
    try:
        calendario = calendario_vacunacion(
            dueno, mascota_id, request.GET.get('mes'),
        )
    except MascotaNoEncontrada:
        raise Http404('Mascota no encontrada.')
    return render(request, 'clinica/vacunas.html', {
        'mascotas': mascotas,
        'calendario': calendario,
    })


@dueno_requerido
def vacuna_turno_view(request, dueno, turno_id):
    try:
        turno = detalle_turno_vacuna(dueno, turno_id)
    except TurnoVacunaNoEncontrado:
        raise Http404('Turno no encontrado.')
    return render(request, 'clinica/vacuna_turno.html', {
        'turno': turno,
        'mes': mes_de_turno(turno),
    })


@dueno_requerido
def vacuna_reservar_view(request, dueno):
    """Tres pasos segun los parametros recibidos: 1) elegir vacuna,
    2) elegir horario, 3) confirmar (POST reserva)."""
    datos = request.POST if request.method == 'POST' else request.GET
    mascota = _mascota_o_404(dueno, datos.get('mascota'))
    url_paso_1 = _url_con_parametros(
        'clinica:vacuna_reservar', mascota=mascota.pk,
    )

    # Paso 1: elegir la vacuna.
    if not datos.get('vacuna'):
        return render(request, 'clinica/vacuna_reservar.html', {
            'paso': 1,
            'mascota': mascota,
            'vacunas': vacunas_para_mascota(mascota),
        })
    try:
        vacuna = obtener_vacuna_para_mascota(mascota, datos.get('vacuna'))
    except VacunaNoEncontrada:
        raise Http404('Vacuna no encontrada.')
    except VacunaError as error:
        messages.error(request, str(error))
        return redirect(url_paso_1)
    url_paso_2 = _url_con_parametros(
        'clinica:vacuna_reservar', mascota=mascota.pk, vacuna=vacuna.pk,
    )

    # Paso 2: elegir el horario.
    veterinario_id = datos.get('veterinario')
    fecha_hora = datos.get('fecha_hora')
    if not (veterinario_id and fecha_hora):
        return render(request, 'clinica/vacuna_reservar.html', {
            'paso': 2,
            'mascota': mascota,
            'vacuna': vacuna,
            'horarios': horarios_libres_vacunacion(),
        })

    # Paso 3: confirmar. El POST reserva.
    try:
        if request.method == 'POST':
            turno = reservar_turno_vacuna(
                dueno, mascota.pk, vacuna.pk, veterinario_id, fecha_hora,
            )
            messages.success(
                request,
                f'¡Turno de {vacuna.nombre} reservado para '
                f'{mascota.nombre}!',
            )
            return redirect(_url_con_parametros(
                'clinica:vacunas',
                mascota=mascota.pk,
                mes=mes_de_turno(turno),
            ))
        horario = obtener_horario_libre(veterinario_id, fecha_hora)
    except VacunaError as error:
        messages.error(request, str(error))
        return redirect(url_paso_2)
    return render(request, 'clinica/vacuna_reservar.html', {
        'paso': 3,
        'mascota': mascota,
        'vacuna': vacuna,
        'horario': horario,
    })
