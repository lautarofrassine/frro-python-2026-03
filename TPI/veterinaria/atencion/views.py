from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from clinica.models import Mascota # Importar modelo Mascota

from atencion.forms import TriageForm
from atencion.services.triage import clasificar_urgencia
from atencion.services.turnos import (
    obtener_turnos_disponibles, 
    asignar_turno_automatico, 
    crear_turno_manual
)

@login_required
def triage_view(request):
    # 1. VALIDACIÓN DE MASCOTAS
    # Verificamos si el usuario tiene al menos una mascota.
    # (Acordate de cambiar 'dueno=request.user' según tu modelo)
    tiene_mascotas = Mascota.objects.filter(dueno__usuario=request.user).exists()
    
    if not tiene_mascotas:
        messages.warning(request, "Tenés que agregar al menos una mascota antes de solicitar un turno por Triage.")
        # Cambiá 'url_agregar_mascota' por el name real de tu ruta
        return redirect('url_agregar_mascota') 

    # 2. PROCESAMIENTO DEL FORMULARIO
    if request.method == 'POST':
        # Le pasamos el usuario logueado al form para que filtre el select
        form = TriageForm(request.POST, usuario=request.user)
        
        if form.is_valid():
            datos = form.a_datos_triage()
            resultado = clasificar_urgencia(datos)
            
            # Extraemos la mascota y el nivel
            mascota_id = form.cleaned_data.get('mascota').id
            nivel_str = resultado['nivel']
            tipo_consulta = "Triage"

            if nivel_str == 'CRITICA':
                try:
                    turno_asignado = asignar_turno_automatico(mascota_id, nivel_str, tipo_consulta)
                    return render(request, 'atencion/turno_confirmado.html', {'turno': turno_asignado})
                except ValueError as error:
                    return render(request, 'atencion/triage_error.html', {'mensaje': str(error)})
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
        # En el GET también hay que pasarle el usuario para que dibuje el select
        form = TriageForm(usuario=request.user)
        
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
        
        
        return render(request, 'atencion/turno_confirmado.html', {'turno': turno_creado})