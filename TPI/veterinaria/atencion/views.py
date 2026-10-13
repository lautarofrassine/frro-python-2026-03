from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import Http404

from atencion.forms import TriageForm
from atencion.services.triage import evaluar_mascota
from atencion.services.turnos import (
    asignar_turno_automatico,
    crear_turno_manual,
    historial_turnos,
    obtener_turnos_disponibles,
    proximos_turnos,
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

            nivel_str = resultado['nivel'] if resultado else None
            tipo_consulta = "Triage"

            if resultado is None:
                pass
            elif nivel_str == 'CRITICA':
                try:
                    turno_asignado = asignar_turno_automatico(
                        mascota_id, nivel_str, tipo_consulta,
                    )
                    return render(
                        request,
                        'atencion/turno_confirmado.html',
                        {'turno': turno_asignado},
                    )
                except ValueError as error:
                    return render(
                        request,
                        'atencion/triage_error.html',
                        {'mensaje': str(error)},
                    )
            else:
                turnos_libres = obtener_turnos_disponibles(dias_adelante=7)
                return render(
                    request,
                    'atencion/triage_resultado.html',
                    {
                        'resultado': resultado,
                        'turnos_libres': turnos_libres,
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
    if request.method == 'POST':
        mascota_id = request.POST.get('mascota_id')
        nivel_urgencia_str = request.POST.get('nivel_urgencia')

        # 1. Obtenemos el string combinado del select y lo dividimos
        seleccion = request.POST.get('fecha_hora_y_vet')
        fecha_hora_str, veterinario_id = seleccion.split('|')

        # 2. Delegamos la creación al servicio
        turno_creado = crear_turno_manual(
            mascota_id=mascota_id,
            nivel_urgencia_str=nivel_urgencia_str,
            tipo="Consulta Regular",
            veterinario_id=veterinario_id,
            fecha_hora=fecha_hora_str
        )

        return render(
            request,
            'atencion/turno_confirmado.html',
            {'turno': turno_creado},
        )
