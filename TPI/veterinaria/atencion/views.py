from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

from atencion.forms import TriageForm
from atencion.services.triage import clasificar_urgencia
from atencion.services.turnos import (
    asignar_turno_automatico,
    crear_turno_manual,
    obtener_turnos_disponibles,
)
from clinica.services.mascotas import listar_mascotas
from clinica.services.usuarios import obtener_dueno_de_usuario


@login_required
def triage_view(request):
    # 1. VALIDACIÓN DE MASCOTAS
    # Regla de capas: las mascotas se piden al service, la vista no
    # consulta modelos. Solo se listan las activas del dueño logueado.
    mascotas = listar_mascotas(obtener_dueno_de_usuario(request.user))

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
            datos = form.a_datos_triage()
            resultado = clasificar_urgencia(datos)

            # Extraemos la mascota y el nivel
            mascota_id = form.cleaned_data['mascota']
            nivel_str = resultado['nivel']
            tipo_consulta = "Triage"

            if nivel_str == 'CRITICA':
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

    return render(request, 'atencion/triage_form.html', {'form': form})


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
