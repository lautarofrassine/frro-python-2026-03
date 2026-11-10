# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from administracion.services.pagos import (
    pago_de_turno,
    tope_restante_del_mes,
)
from administracion.services.obras_sociales import (
    ObraSocialError,
    asignar_obra_social_a_dueno,
    listar_obras_sociales_activas,
)
from atencion.permisos import rechazar_veterinarios
from atencion.services.veterinarios import obtener_veterinario_de_usuario
from clinica.forms import (
    CambiarEmailForm,
    CambiarPasswordForm,
    DatosPersonalesForm,
    LoginForm,
    MascotaForm,
    ObraSocialForm,
    RegistroForm,
)
from clinica.services.historias import (
    historia_de_mascota_para_dueno,
    mascotas_para_historia,
)
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
    CuentaError,
    RegistroError,
    actualizar_datos_personales,
    cambiar_email,
    cambiar_password,
    obtener_dueno_de_usuario,
    registrar_dueno,
)
from clinica.services.vacunas import (
    TurnoVacunaNoEncontrado,
    VacunaError,
    VacunaNoEncontrada,
    calendario_vacunacion,
    detalle_turno_vacuna,
    calendario_de_horarios_vacunacion,
    horarios_vacunacion_del_dia,
    interpretar_dia,
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

    # Paso 2: elegir el dia en el calendario y despues el horario.
    veterinario_id = datos.get('veterinario')
    fecha_hora = datos.get('fecha_hora')
    if not (veterinario_id and fecha_hora):
        dia = interpretar_dia(request.GET.get('dia'))
        mes = request.GET.get('mes') or (
            dia.strftime('%Y-%m') if dia else None
        )
        return render(request, 'clinica/vacuna_reservar.html', {
            'paso': 2,
            'mascota': mascota,
            'vacuna': vacuna,
            'calendario': calendario_de_horarios_vacunacion(mes),
            'dia': dia,
            'horarios': horarios_vacunacion_del_dia(dia) if dia else [],
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
            # Resumen con el monto y las opciones de pago.
            return redirect(
                'pagos:confirmacion', pago_id=pago_de_turno(turno).pk,
            )
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


def _guardar_datos_personales(request, dueno, obras_sociales):
    form = DatosPersonalesForm(request.POST)
    if form.is_valid():
        try:
            actualizar_datos_personales(dueno, **form.cleaned_data)
        except RegistroError as error:
            form.add_error(error.campo, str(error))
        else:
            return form, 'Se guardaron tus datos personales.'
    return form, None


def _guardar_obra_social(request, dueno, obras_sociales):
    form = ObraSocialForm(request.POST, obras_sociales=obras_sociales)
    if form.is_valid():
        try:
            asignar_obra_social_a_dueno(dueno, **form.datos_obra_social())
        except ObraSocialError as error:
            form.add_error(error.campo, str(error))
        else:
            return form, 'Se guardó tu obra social.'
    return form, None


def _guardar_email(request, dueno, obras_sociales):
    form = CambiarEmailForm(request.POST)
    if form.is_valid():
        try:
            cambiar_email(
                dueno,
                form.cleaned_data['nuevo_email'],
                form.cleaned_data['password_actual'],
            )
        except CuentaError as error:
            form.add_error(error.campo, str(error))
        else:
            return form, (
                f'Tu email ahora es {dueno.email}. Usalo para ingresar.'
            )
    return form, None


def _guardar_password(request, dueno, obras_sociales):
    form = CambiarPasswordForm(request.user, request.POST)
    if form.is_valid():
        try:
            cambiar_password(
                request.user,
                form.cleaned_data['old_password'],
                form.cleaned_data['new_password1'],
            )
        except CuentaError as error:
            form.add_error(error.campo, str(error))
        else:
            # Sin esto, cambiar la contraseña cierra la sesion.
            update_session_auth_hash(request, request.user)
            return form, 'Se cambió tu contraseña.'
    return form, None


# Cada seccion de Mi perfil tiene su formulario: guardar una no toca las
# demas. El POST indica cual con el campo oculto "seccion".
GUARDAR_SECCION_PERFIL = {
    'datos': _guardar_datos_personales,
    'obra_social': _guardar_obra_social,
    'email': _guardar_email,
    'password': _guardar_password,
}


@dueno_requerido
def perfil_view(request, dueno):
    obras_sociales = listar_obras_sociales_activas()
    formularios = {
        'datos': DatosPersonalesForm.desde_dueno(dueno),
        'obra_social': ObraSocialForm.desde_dueno(dueno, obras_sociales),
        'email': CambiarEmailForm(),
        'password': CambiarPasswordForm(request.user),
    }
    if request.method == 'POST':
        seccion = request.POST.get('seccion')
        guardar = GUARDAR_SECCION_PERFIL.get(seccion)
        if guardar is None:
            return redirect('clinica:perfil')
        form, mensaje = guardar(request, dueno, obras_sociales)
        if mensaje:
            messages.success(request, mensaje)
            return redirect('clinica:perfil')
        formularios[seccion] = form
    return render(request, 'clinica/perfil.html', {
        'form_datos': formularios['datos'],
        'form_obra_social': formularios['obra_social'],
        'form_email': formularios['email'],
        'form_password': formularios['password'],
        'dueno': dueno,
        'obras_sociales': obras_sociales,
        'tope_restante': tope_restante_del_mes(dueno),
    })


# ---------------------------------------------------------------------
# Historia clinica (solo lectura para el dueño)
# ---------------------------------------------------------------------

@dueno_requerido
def historias_view(request, dueno):
    """Con una sola mascota va directo a su historia; con varias, se
    elige una."""
    mascotas = mascotas_para_historia(dueno)
    if len(mascotas) == 1:
        return redirect('clinica:historia', mascota_id=mascotas[0].pk)
    return render(request, 'clinica/historias.html', {'mascotas': mascotas})


@dueno_requerido
def historia_view(request, dueno, mascota_id):
    try:
        historia = historia_de_mascota_para_dueno(dueno, mascota_id)
    except MascotaNoEncontrada:
        raise Http404('Mascota no encontrada.')
    return render(request, 'clinica/historia.html', {
        **historia,
        'varias_mascotas': len(mascotas_para_historia(dueno)) > 1,
    })
