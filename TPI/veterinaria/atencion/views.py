from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from atencion.forms import TriageForm
from atencion.services.triage import evaluar_mascota
from atencion.services.turnos import (
    TIPO_CONSULTA,
    TurnoError,
    TurnoNoEncontrado,
    asignar_turno_automatico,
    cancelar_turno,
    historial_turnos,
    obtener_turno_de_dueno,
    proximos_turnos,
    puede_cancelarse,
    reservar_turno,
    turnos_disponibles,
)
from clinica.services.mascotas import (
    MascotaError,
    MascotaNoEncontrada,
    listar_mascotas,
)
from clinica.services.usuarios import obtener_dueno_de_usuario


@login_required
def consultas_view(request):
    # El personal de la clinica no tiene Dueno: los services devuelven
    # listas vacias y la plantilla muestra un mensaje.
    dueno = obtener_dueno_de_usuario(request.user)
    return render(request, 'atencion/consultas.html', {
        'dueno': dueno,
        'proximos': proximos_turnos(dueno),
        'historial': historial_turnos(dueno),
    })


@login_required
def triage_view(request):
    # 1. VALIDACIÓN DE MASCOTAS
    # Regla de capas: las mascotas se piden al service, la vista no
    # consulta modelos. Solo se listan las activas del dueño logueado.
    dueno = obtener_dueno_de_usuario(request.user)
    mascotas = listar_mascotas(dueno)
    # Si la mascota elegida no tiene fecha de nacimiento, la plantilla
    # muestra el link para completarla.
    mascota_a_completar = None

    if not mascotas:
        messages.warning(
            request,
            'Tenés que agregar al menos una mascota antes de solicitar '
            'un turno por Triage.',
        )
        return redirect('clinica:mascota_nueva')

    # 2. PROCESAMIENTO DEL FORMULARIO
    if request.method == 'POST':
        # Le pasamos las mascotas del dueño para que arme el select
        form = TriageForm(request.POST, mascotas=mascotas)

        if form.is_valid():
            mascota_id = form.cleaned_data['mascota']
            try:
                # La edad y la especie las pone el service a partir de
                # la mascota; la vista no calcula nada.
                resultado = evaluar_mascota(
                    dueno, mascota_id, form.a_datos_triage(),
                )
            except MascotaNoEncontrada:
                raise Http404('Mascota no encontrada.')
            except MascotaError as error:
                form.add_error('mascota', str(error))
                mascota_a_completar = mascota_id
                resultado = None

            if resultado is not None:
                if resultado['nivel'] == 'CRITICA':
                    # Urgencia: se reserva solo el horario mas proximo.
                    try:
                        turno_asignado = asignar_turno_automatico(
                            dueno, mascota_id, resultado['nivel'],
                        )
                    except TurnoError as error:
                        messages.error(request, str(error))
                    else:
                        return render(
                            request,
                            'atencion/turno_confirmado.html',
                            {'turno': turno_asignado},
                        )
                return render(
                    request,
                    'atencion/triage_resultado.html',
                    {
                        'resultado': resultado,
                        'turnos_libres': turnos_disponibles(),
                        'mascota_id': mascota_id,
                    }
                )
    else:
        # En el GET también hay que pasarle las mascotas para el select
        form = TriageForm(mascotas=mascotas)

    return render(request, 'atencion/triage_form.html', {
        'form': form,
        'mascota_a_completar': mascota_a_completar,
    })


@login_required
def confirmar_turno_seleccionado_view(request):
    if request.method != 'POST':
        return redirect('atencion:triage')

    # El select del resultado del triage manda "fecha_hora|veterinario".
    fecha_hora, _, veterinario_id = (
        request.POST.get('fecha_hora_y_vet', '').partition('|')
    )
    try:
        turno_creado = reservar_turno(
            obtener_dueno_de_usuario(request.user),
            request.POST.get('mascota_id'),
            veterinario_id,
            fecha_hora,
            nivel_urgencia=request.POST.get('nivel_urgencia'),
            tipo=TIPO_CONSULTA,
        )
    except TurnoError as error:
        messages.error(request, str(error))
        return redirect('atencion:triage')

    return render(
        request,
        'atencion/turno_confirmado.html',
        {'turno': turno_creado},
    )


@login_required
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
