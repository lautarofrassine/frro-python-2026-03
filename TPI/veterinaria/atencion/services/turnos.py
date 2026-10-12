from datetime import datetime, timedelta
from django.utils import timezone
from atencion.models import Turno, Veterinario, NivelUrgencia, HorarioAtencion

def obtener_turnos_disponibles(dias_adelante=7):
    """
    Regla de Negocio: Genera y devuelve una lista de diccionarios con los turnos libres.
    Retorna tipos de datos básicos (list, dict) para no acoplar la vista a modelos complejos.
    """
    ahora = timezone.now()
    duracion_turno = timedelta(minutes=30)
    disponibles = []

    # Buscamos turnos ocupados para optimizar y no golpear la base de datos en el bucle
    turnos_ocupados = Turno.objects.filter(
        fecha_hora__gte=ahora,
        fecha_hora__lte=ahora + timedelta(days=dias_adelante),
        estado__in=[Turno.Estado.PENDIENTE, Turno.Estado.EN_CURSO]
    ).values_list('veterinario_id', 'fecha_hora')

    # Convertimos a Set para buscar rápido en memoria
    ocupados_set = {(t[0], t[1]) for t in turnos_ocupados}

    for dias in range(dias_adelante):
        fecha_busqueda = ahora.date() + timedelta(days=dias)
        dia_semana = fecha_busqueda.weekday()

        horarios = HorarioAtencion.objects.filter(
            dia_semana=dia_semana,
            veterinario__estado=Veterinario.Estado.ACTIVO
        ).select_related('veterinario')

        for regla in horarios:
            hora_actual = timezone.make_aware(datetime.combine(fecha_busqueda, regla.hora_inicio))
            hora_fin = timezone.make_aware(datetime.combine(fecha_busqueda, regla.hora_fin))

            # Si es el día de hoy, adelantamos el puntero a la próxima media hora
            if hora_actual < ahora:
                hora_actual = ahora.replace(minute=30 if ahora.minute >= 30 else 0, second=0, microsecond=0)
                if ahora.minute >= 30:
                    hora_actual += timedelta(hours=1)

            # Generamos los slots
            while hora_actual + duracion_turno <= hora_fin:
                if (regla.veterinario.id, hora_actual) not in ocupados_set:
                    disponibles.append({
                        'fecha_hora': hora_actual,
                        'veterinario_id': regla.veterinario.id,
                        'veterinario_nombre': regla.veterinario.nombre
                    })
                hora_actual += duracion_turno

    # Ordenar cronológicamente del más cercano al más lejano
    disponibles.sort(key=lambda x: x['fecha_hora'])
    return disponibles


def asignar_turno_automatico(mascota_id, nivel_urgencia_str, tipo):
    """
    Regla de Negocio: Busca el turno libre más próximo y lo reserva automáticamente.
    Lanzado cuando el triage es CRITICA.
    """
    turnos_libres = obtener_turnos_disponibles(dias_adelante=7)
    
    if not turnos_libres:
        raise ValueError("No hay veterinarios disponibles para atender la urgencia.")

    # El más cercano siempre está en la posición 0 gracias al sort()
    turno_elegido = turnos_libres[0]

    return crear_turno_manual(
        mascota_id=mascota_id,
        nivel_urgencia_str=nivel_urgencia_str,
        tipo=tipo,
        veterinario_id=turno_elegido['veterinario_id'],
        fecha_hora=turno_elegido['fecha_hora']
    )


def crear_turno_manual(mascota_id, nivel_urgencia_str, tipo, veterinario_id, fecha_hora):
    """
    Crea un turno en la base de datos aislando los modelos de la vista.
    Acepta 'fecha_hora' como string (del form) o como objeto datetime.
    """
    if isinstance(fecha_hora, str):
        fecha_hora = timezone.datetime.fromisoformat(fecha_hora)

    urgencia_obj = NivelUrgencia.objects.get(nivel_urgencia=nivel_urgencia_str)
    
    turno = Turno.objects.create(
        mascota_id=mascota_id,
        veterinario_id=veterinario_id,
        nivel_urgencia=urgencia_obj,
        fecha_hora=fecha_hora,
        tipo=tipo,
        estado=Turno.Estado.PENDIENTE
    )
    return turno

def cambiar_estado_turno(turno, nuevo_estado):
    """Cambia el estado de un Turno validando las transiciones permitidas."""
    # Acá implementás tu lógica futura
    pass