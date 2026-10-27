# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from atencion.forms import EntradaHistoriaForm, TriageForm
from atencion.permisos import (
    rechazar_veterinarios,
    solo_duenos,
    veterinario_requerido,
)
from atencion.services.agenda import (
    agenda_semanal,
    obtener_turno_del_veterinario,
    turnos_de_hoy,
)
from atencion.services.turnos import (
    SeleccionInvalida,
    TurnoError,
    TurnoNoEncontrado,
    cancelar_turno,
    especialidades_para_turno,
    historial_turnos,
    horario_para_consulta,
    obtener_especialidad_para_turno,
    obtener_turno_de_dueno,
    proximos_turnos,
    puede_cancelarse,
    reservar_turno_de_consulta,
    semana_de_turnos,
)
from atencion.services.urgencias import (
    atender_urgencia,
    confirmar_turno_de_guardia,
)
from clinica.services.mascotas import (
    MascotaError,
    MascotaNoEncontrada,
    listar_mascotas,
    obtener_mascota_de_dueno,
)
from clinica.services.historias import (
    EntradaAjena,
    EntradaNoEncontrada,
    HistoriaError,
    cargar_entrada,
    editar_entrada,
    historia_clinica,
    mascotas_atendidas,
    obtener_entrada_propia,
    obtener_mascota_atendida,
    obtener_turno_para_entrada,
)
from clinica.services.usuarios import obtener_dueno_de_usuario

LARGO_MAXIMO_MOTIVO = 500


def _url_con_parametros(nombre, **parametros):
    return f'{reverse(nombre)}?{urlencode(parametros)}'


def _cuando(fecha_hora):
    """('jueves 15 de octubre', '10:00') en hora local, para mensajes."""
    local = timezone.localtime(fecha_hora)
    return date_format(local, r'l j \d\e F'), date_format(local, 'H:i')


@solo_duenos
def consultas_view(request):
    # El personal de la clinica no tiene Dueno: los services devuelven
    # listas vacias y la plantilla muestra un mensaje.
    dueno = obtener_dueno_de_usuario(request.user)
    return render(request, 'atencion/consultas.html', {
        'dueno': dueno,
        'proximos': proximos_turnos(dueno),
        'historial': historial_turnos(dueno),
    })


# ---------------------------------------------------------------------
# Urgencia
# ---------------------------------------------------------------------

def urgencia_view(request):
    """Sin sesion muestra como llegar a la guardia y los botones para
    ingresar. Con sesion, el formulario de triage; al enviarlo, el
    service decide que hacer segun el nivel de urgencia."""
    if not request.user.is_authenticated:
        if request.method == 'POST':
            return redirect_to_login(reverse('atencion:urgencia'))
        return render(request, 'atencion/urgencia.html', {'form': None})
    rechazar_veterinarios(request)

    dueno = obtener_dueno_de_usuario(request.user)
    mascotas = listar_mascotas(dueno)
    if not mascotas:
        messages.warning(
            request,
            'Tenés que agregar al menos una mascota para que podamos '
            'evaluarla.',
        )
        return redirect('clinica:mascota_nueva')

    # Si la mascota elegida no tiene fecha de nacimiento, la plantilla
    # muestra el link para completarla.
    mascota_a_completar = None
    if request.method == 'POST':
        form = TriageForm(request.POST, mascotas=mascotas)
        if form.is_valid():
            mascota_id = form.cleaned_data['mascota']
            try:
                resultado = atender_urgencia(
                    dueno, mascota_id, form.a_datos_triage(),
                )
            except MascotaNoEncontrada:
                raise Http404('Mascota no encontrada.')
            except MascotaError as error:
                form.add_error('mascota', str(error))
                mascota_a_completar = mascota_id
            else:
                return render(
                    request,
                    'atencion/urgencia_resultado.html',
                    {'resultado': resultado},
                )
    else:
        form = TriageForm(mascotas=mascotas)

    return render(request, 'atencion/urgencia.html', {
        'form': form,
        'mascota_a_completar': mascota_a_completar,
    })


@solo_duenos
@require_POST
def urgencia_confirmar_view(request):
    """Confirma el turno de guardia propuesto para una urgencia ALTA."""
    try:
        turno = confirmar_turno_de_guardia(
            obtener_dueno_de_usuario(request.user),
            request.POST.get('mascota'),
            request.POST.get('veterinario'),
            request.POST.get('fecha_hora'),
        )
    except TurnoError as error:
        messages.error(request, str(error))
        return redirect('atencion:urgencia')

    dia, hora = _cuando(turno.fecha_hora)
    messages.success(
        request,
        f'Turno de guardia reservado para {turno.mascota.nombre}: {dia} '
        f'a las {hora} con {turno.veterinario.nombre}.',
    )
    return redirect('atencion:consultas')


# ---------------------------------------------------------------------
# Sacar turno: 1 Mascota - 2 Especialidad - 3 Dia y horario
# ---------------------------------------------------------------------

def _mascota_o_404(dueno, mascota_id):
    try:
        return obtener_mascota_de_dueno(dueno, mascota_id)
    except MascotaNoEncontrada:
        raise Http404('Mascota no encontrada.')


@solo_duenos
def turno_nuevo_view(request):
    dueno = obtener_dueno_de_usuario(request.user)

    # Paso 1: elegir la mascota.
    if not request.GET.get('mascota'):
        return render(request, 'atencion/turno_nuevo.html', {
            'paso': 1,
            'mascotas': listar_mascotas(dueno),
        })
    mascota = _mascota_o_404(dueno, request.GET.get('mascota'))

    # Paso 2: elegir la especialidad.
    if not request.GET.get('especialidad'):
        return render(request, 'atencion/turno_nuevo.html', {
            'paso': 2,
            'mascota': mascota,
            'especialidades': especialidades_para_turno(),
        })

    # Paso 3: elegir dia y horario.
    try:
        especialidad = obtener_especialidad_para_turno(
            request.GET.get('especialidad'),
        )
        semana = semana_de_turnos(
            especialidad['codigo'],
            request.GET.get('veterinario'),
            request.GET.get('semana'),
        )
    except SeleccionInvalida:
        raise Http404('Especialidad o veterinario no disponible.')
    return render(request, 'atencion/turno_nuevo.html', {
        'paso': 3,
        'mascota': mascota,
        'especialidad': especialidad,
        'semana': semana,
    })


@solo_duenos
def turno_confirmar_view(request):
    """GET muestra la confirmacion; POST reserva y va a Mis consultas.
    Si el horario ya fue tomado, vuelve al paso 3 con el error."""
    dueno = obtener_dueno_de_usuario(request.user)
    datos = request.POST if request.method == 'POST' else request.GET
    mascota = _mascota_o_404(dueno, datos.get('mascota'))
    codigo = datos.get('especialidad')
    veterinario_id = datos.get('veterinario')
    fecha_hora = datos.get('fecha_hora')
    url_paso_3 = _url_con_parametros(
        'atencion:turno_nuevo', mascota=mascota.pk, especialidad=codigo,
    )

    try:
        if request.method == 'POST':
            turno = reservar_turno_de_consulta(
                dueno,
                mascota.pk,
                codigo,
                veterinario_id,
                fecha_hora,
                motivo=request.POST.get('motivo', '').strip()[
                    :LARGO_MAXIMO_MOTIVO
                ],
            )
            dia, hora = _cuando(turno.fecha_hora)
            messages.success(
                request,
                f'¡Turno reservado para {mascota.nombre} el {dia} a las '
                f'{hora}!',
            )
            return redirect('atencion:consultas')
        horario = horario_para_consulta(codigo, veterinario_id, fecha_hora)
    except SeleccionInvalida:
        raise Http404('Especialidad o veterinario no disponible.')
    except TurnoError as error:
        messages.error(request, str(error))
        return redirect(url_paso_3)

    return render(request, 'atencion/turno_confirmar.html', {
        'mascota': mascota,
        'horario': horario,
        'url_paso_3': url_paso_3,
        'largo_maximo_motivo': LARGO_MAXIMO_MOTIVO,
    })


# ---------------------------------------------------------------------
# Cancelacion
# ---------------------------------------------------------------------

@solo_duenos
def turno_cancelar_view(request, turno_id):
    """GET muestra la confirmacion; POST cancela. `siguiente` indica a
    donde volver (Mis consultas por defecto)."""
    dueno = obtener_dueno_de_usuario(request.user)
    siguiente = request.POST.get('siguiente') or request.GET.get('siguiente')
    if not url_has_allowed_host_and_scheme(
        siguiente, allowed_hosts={request.get_host()},
    ):
        siguiente = reverse('atencion:consultas')

    try:
        if request.method == 'POST':
            turno = cancelar_turno(dueno, turno_id)
            messages.success(
                request,
                f'Se canceló el turno de {turno.mascota.nombre}.',
            )
            return redirect(siguiente)
        turno = obtener_turno_de_dueno(dueno, turno_id)
    except TurnoNoEncontrado:
        raise Http404('Turno no encontrado.')
    except TurnoError as error:
        messages.error(request, str(error))
        return redirect(siguiente)

    if not puede_cancelarse(turno):
        messages.error(request, 'Este turno ya no se puede cancelar.')
        return redirect(siguiente)
    return render(request, 'atencion/turno_cancelar.html', {
        'turno': turno,
        'siguiente': siguiente,
    })


# ---------------------------------------------------------------------
# Veterinarios: agenda e historias clinicas (/veterinario/...)
# ---------------------------------------------------------------------

@veterinario_requerido
def agenda_view(request, veterinario):
    return render(request, 'atencion/vet_agenda.html', {
        'veterinario': veterinario,
        'agenda': agenda_semanal(veterinario, request.GET.get('semana')),
        'turnos_hoy': turnos_de_hoy(veterinario),
    })


@veterinario_requerido
def vet_turno_view(request, veterinario, turno_id):
    try:
        turno = obtener_turno_del_veterinario(veterinario, turno_id)
    except TurnoNoEncontrado:
        raise Http404('Turno no encontrado.')
    return render(request, 'atencion/vet_turno.html', {'turno': turno})


@veterinario_requerido
def historias_view(request, veterinario):
    buscar = request.GET.get('q', '').strip()
    return render(request, 'atencion/vet_historias.html', {
        'mascotas': mascotas_atendidas(veterinario, buscar),
        'buscar': buscar,
    })


def _mascota_atendida_o_404(veterinario, mascota_id):
    try:
        return obtener_mascota_atendida(veterinario, mascota_id)
    except MascotaNoEncontrada:
        raise Http404('Mascota no encontrada.')


@veterinario_requerido
def historia_view(request, veterinario, mascota_id):
    mascota = _mascota_atendida_o_404(veterinario, mascota_id)
    return render(request, 'atencion/vet_historia.html', {
        'veterinario': veterinario,
        'mascota': mascota,
        'entradas': historia_clinica(mascota),
    })


@veterinario_requerido
def entrada_nueva_view(request, veterinario, mascota_id):
    """Formulario de nueva entrada. Si viene ?turno=ID (desde el detalle
    del turno), la entrada queda asociada a ese turno."""
    mascota = _mascota_atendida_o_404(veterinario, mascota_id)
    datos = request.POST if request.method == 'POST' else request.GET
    turno_id = datos.get('turno') or None
    try:
        turno = obtener_turno_para_entrada(veterinario, mascota, turno_id)
    except HistoriaError:
        raise Http404('Turno no encontrado.')

    if request.method == 'POST':
        form = EntradaHistoriaForm(request.POST)
        if form.is_valid():
            try:
                cargar_entrada(
                    veterinario, mascota.pk, turno_id=turno_id,
                    **form.datos_entrada(),
                )
            except HistoriaError as error:
                form.add_error(error.campo, str(error))
            else:
                messages.success(
                    request,
                    'Entrada guardada en la historia clínica de '
                    f'{mascota.nombre}.',
                )
                return redirect('veterinario:historia', mascota_id=mascota.pk)
    else:
        form = EntradaHistoriaForm()
    return render(request, 'atencion/vet_entrada_form.html', {
        'form': form,
        'mascota': mascota,
        'turno': turno,
        'entrada': None,
    })


@veterinario_requerido
def entrada_editar_view(request, veterinario, entrada_id):
    """Solo las entradas propias; las de otro veterinario dan 403."""
    try:
        entrada = obtener_entrada_propia(veterinario, entrada_id)
        if request.method == 'POST':
            form = EntradaHistoriaForm(request.POST)
            if form.is_valid():
                try:
                    editar_entrada(
                        veterinario, entrada.pk, **form.datos_entrada(),
                    )
                except HistoriaError as error:
                    form.add_error(error.campo, str(error))
                else:
                    messages.success(request, 'Se actualizó la entrada.')
                    return redirect(
                        'veterinario:historia',
                        mascota_id=entrada.mascota_id,
                    )
        else:
            form = EntradaHistoriaForm.desde_entrada(entrada)
    except EntradaNoEncontrada:
        raise Http404('Entrada no encontrada.')
    except EntradaAjena:
        raise PermissionDenied('Solo podés editar tus propias entradas.')
    return render(request, 'atencion/vet_entrada_form.html', {
        'form': form,
        'mascota': entrada.mascota,
        'turno': entrada.turno,
        'entrada': entrada,
    })
