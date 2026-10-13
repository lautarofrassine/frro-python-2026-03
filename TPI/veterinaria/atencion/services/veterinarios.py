from datetime import time

from django.db import transaction

from atencion.models import HorarioAtencion, Veterinario

# Franjas de atencion. HorarioAtencion guarda una fila por veterinario
# y dia; los turnos de 30 minutos se calculan entre hora_inicio y
# hora_fin (ver services/turnos.py).
MANANA = (time(8, 0), time(13, 0))
TARDE = (time(13, 0), time(19, 0))
DIAS_DE_ATENCION = (
    HorarioAtencion.DiaSemana.LUNES,
    HorarioAtencion.DiaSemana.MARTES,
    HorarioAtencion.DiaSemana.MIERCOLES,
    HorarioAtencion.DiaSemana.JUEVES,
    HorarioAtencion.DiaSemana.VIERNES,
    HorarioAtencion.DiaSemana.SABADO,
)

_E = Veterinario.Especialidad

# Datos ficticios: 3 veterinarios por especialidad de consulta. En cada
# una hay al menos uno de mañana y uno de tarde. Las matriculas MP-50xx
# no chocan con las ya cargadas (MP-1234, MP-5678, MP-9012).
VETERINARIOS_INICIALES = [
    ('MP-5001', 'Dra. Laura Fernández', _E.CLINICA_GENERAL, MANANA),
    ('MP-5002', 'Dr. Martín Sosa', _E.CLINICA_GENERAL, TARDE),
    ('MP-5003', 'Dra. Carolina Benítez', _E.CLINICA_GENERAL, MANANA),
    ('MP-5004', 'Dr. Federico Acosta', _E.CARDIOLOGIA, MANANA),
    ('MP-5005', 'Dra. Valeria Medina', _E.CARDIOLOGIA, TARDE),
    ('MP-5006', 'Dr. Gonzalo Herrera', _E.CARDIOLOGIA, TARDE),
    ('MP-5007', 'Dra. Florencia Aguirre', _E.DERMATOLOGIA, MANANA),
    ('MP-5008', 'Dr. Nicolás Cabrera', _E.DERMATOLOGIA, TARDE),
    ('MP-5009', 'Dra. Julieta Molina', _E.DERMATOLOGIA, MANANA),
    ('MP-5010', 'Dr. Sebastián Romero', _E.TRAUMATOLOGIA, MANANA),
    ('MP-5011', 'Dra. Micaela Castro', _E.TRAUMATOLOGIA, TARDE),
    ('MP-5012', 'Dr. Agustín Ledesma', _E.TRAUMATOLOGIA, TARDE),
    ('MP-5013', 'Dra. Camila Ortiz', _E.GASTROENTEROLOGIA, MANANA),
    ('MP-5014', 'Dr. Ezequiel Villalba', _E.GASTROENTEROLOGIA, TARDE),
    ('MP-5015', 'Dra. Rocío Peralta', _E.GASTROENTEROLOGIA, MANANA),
    ('MP-5016', 'Dr. Tomás Giménez', _E.OFTALMOLOGIA, MANANA),
    ('MP-5017', 'Dra. Antonella Luna', _E.OFTALMOLOGIA, TARDE),
    ('MP-5018', 'Dr. Ramiro Correa', _E.OFTALMOLOGIA, TARDE),
]

# Los de VACUNACION solo se crean si la clinica todavia no tiene ningun
# veterinario de esa especialidad.
VETERINARIOS_VACUNACION = [
    ('MP-5019', 'Dra. Paula Navarro', _E.VACUNACION, MANANA),
    ('MP-5020', 'Dr. Ignacio Ferreyra', _E.VACUNACION, TARDE),
    ('MP-5021', 'Dra. Milagros Suárez', _E.VACUNACION, MANANA),
]


@transaction.atomic
def cargar_veterinarios_iniciales():
    """Crea los veterinarios de VETERINARIOS_INICIALES que todavia no
    existen (se busca por matricula, asi se puede correr varias veces),
    todos ACTIVO y con su horario de lunes a sabado. Los de VACUNACION
    se crean solo si no hay ninguno de esa especialidad.

    Devuelve {etiqueta_especialidad: {'creados': n, 'existentes': n}}.
    """
    resumen = {
        etiqueta: {'creados': 0, 'existentes': 0}
        for etiqueta in Veterinario.Especialidad.labels
    }
    a_cargar = list(VETERINARIOS_INICIALES)
    de_vacunacion = Veterinario.objects.filter(
        especialidad=Veterinario.Especialidad.VACUNACION,
    ).count()
    if de_vacunacion:
        resumen[Veterinario.Especialidad.VACUNACION.label]['existentes'] = (
            de_vacunacion
        )
    else:
        a_cargar += VETERINARIOS_VACUNACION

    for matricula, nombre, especialidad, franja in a_cargar:
        veterinario, creado = Veterinario.objects.get_or_create(
            matricula=matricula,
            defaults={
                'nombre': nombre,
                'especialidad': especialidad,
                'estado': Veterinario.Estado.ACTIVO,
            },
        )
        if creado:
            hora_inicio, hora_fin = franja
            HorarioAtencion.objects.bulk_create([
                HorarioAtencion(
                    veterinario=veterinario,
                    dia_semana=dia,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
                for dia in DIAS_DE_ATENCION
            ])
        clave = 'creados' if creado else 'existentes'
        resumen[especialidad.label][clave] += 1
    return resumen
