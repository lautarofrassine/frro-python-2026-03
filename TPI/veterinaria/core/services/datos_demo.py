"""Datos de demostracion: dueños, mascotas, turnos, pagos, historias
clinicas y vacunas aplicadas (python manage.py cargar_datos_demo).

- Todos los dueños usan emails @demo.clinicavet24.com: asi se los
  identifica y borrar_datos_demo elimina solo eso.
- Lo que se puede crear con los services se crea con ellos (registro,
  mascotas, reservas con su pago y cobertura, vacunas, cancelaciones).
  Lo pasado, que los services no permiten, se crea directo pero con las
  mismas reglas: dentro del HorarioAtencion del veterinario, sin pisar
  otro turno y con el pago calculado por crear_pago_de_turno.
- Todas las fechas son relativas a hoy.
- Es todo o nada (una transaccion) y no duplica: si ya hay dueños de
  demo, no carga nada.

Los nombres, DNI y telefonos son inventados.
"""
import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from administracion.models import ObraSocial, Pago
from administracion.services.obras_sociales import (
    OBRAS_SOCIALES_INICIALES,
    asignar_obra_social_a_dueno,
)
from administracion.services.pagos import crear_pago_de_turno, marcar_pagado
from atencion.models import NivelUrgencia, Turno, Veterinario
from atencion.services.turnos import (
    TIPO_CONSULTA,
    TIPO_GUARDIA,
    TIPO_VACUNACION,
    cancelar_turno,
    horarios_del_dia,
    reservar_turno,
    turnos_disponibles,
)
from clinica.models import (
    AplicacionVacuna,
    Dueno,
    HistorialClinico,
    Mascota,
    Vacuna,
)
from clinica.services.mascotas import registrar_mascota
from clinica.services.usuarios import RegistroError, registrar_dueno
from clinica.services.vacunas import reservar_turno_vacuna

DOMINIO = '@demo.clinicavet24.com'
EMAIL_PRINCIPAL = f'demo{DOMINIO}'
EMAIL_VETERINARIO_DEMO = 'laura.fernandez@clinicavet24.com'
MATRICULA_VETERINARIO_DEMO = 'MP-5001'
# Semilla fija: con la misma base y el mismo dia, mismos datos.
SEMILLA = 2026
DIAS_FUTURO = 14
DIAS_PASADO = 60

_E = Veterinario.Especialidad
ESPECIALIDADES_CONSULTA = (
    _E.CLINICA_GENERAL, _E.CARDIOLOGIA, _E.DERMATOLOGIA, _E.TRAUMATOLOGIA,
    _E.GASTROENTEROLOGIA, _E.OFTALMOLOGIA,
)
PERRO = 'PERRO'
GATO = 'GATO'
VACUNAS_REQUERIDAS = (
    ('Séxtuple', PERRO), ('Antirrábica', PERRO),
    ('Tos de las perreras', PERRO), ('Triple felina', GATO),
    ('Leucemia felina', GATO), ('Antirrábica', GATO),
)

# (usuario del email, nombre, apellido, DNI, telefono, obra social,
#  [(nombre, especie, raza, edad en meses, peso kg)])
DUENOS = [
    ('demo', 'Valentina', 'Ríos', '33418275', '341 555-2048',
     'VetSalud Plus', [
         ('Rocco', PERRO, 'Labrador Retriever', 48, '30.5'),
         ('Mora', GATO, 'Europeo de pelo corto', 30, '4.2'),
         ('Toby', PERRO, 'Caniche', 4, '2.1'),
     ]),
    ('lucas.gimenez', 'Lucas', 'Giménez', '35902614', '341 536-7712',
     'Huellitas Total', [
         ('Simba', GATO, 'Siamés', 60, '4.8'),
         ('Lola', PERRO, 'Beagle', 36, '11.5'),
     ]),
    ('martina.lopez', 'Martina', 'López', '38257109', '341 642-1189',
     'Mascotas Protegidas', [
         ('Bruno', PERRO, 'Bóxer', 72, '29.0'),
     ]),
    ('julian.paredes', 'Julián', 'Paredes', '31764320', '341 588-0351',
     'PetCare Básico', [
         ('Milo', GATO, 'Persa', 24, '3.9'),
         ('Nala', GATO, 'Mestizo', 3, '1.4'),
     ]),
    ('sofia.alvarez', 'Sofía', 'Álvarez', '36581047', '341 677-4420',
     'VetSalud Plus', [
         ('Coco', PERRO, 'Bulldog Francés', 40, '12.0'),
         ('Kira', PERRO, 'Border Collie', 54, '18.0'),
     ]),
    ('diego.morales', 'Diego', 'Morales', '29846153', '341 529-3367',
     'Huellitas Total', [
         ('Thor', PERRO, 'Golden Retriever', 84, '32.0'),
         ('Luna', GATO, 'Mestizo', 18, '3.6'),
         ('Pepa', PERRO, 'Dachshund', 5, '3.2'),
     ]),
    ('camila.suarez', 'Camila', 'Suárez', '39120586', '341 614-9025',
     'Mascotas Protegidas', [
         ('Oliver', GATO, 'Maine Coon', 42, '7.5'),
     ]),
    ('matias.romero', 'Matías', 'Romero', '34075298', '341 593-6614',
     'VetSalud Plus', [
         ('Zeus', PERRO, 'Pastor Alemán', 60, '34.0'),
         ('Frida', GATO, 'Siamés', 96, '4.1'),
     ]),
    ('agustina.ponce', 'Agustina', 'Ponce', '40318762', '341 655-2870',
     'PetCare Básico', [
         ('Uma', PERRO, 'Mestizo', 26, '14.0'),
     ]),
    ('nicolas.ferrari', 'Nicolás', 'Ferrari', '32659814', '341 547-1936',
     'Huellitas Total', [
         ('Pancho', PERRO, 'Schnauzer Miniatura', 108, '7.8'),
         ('Mía', GATO, 'Mestizo', 14, '3.3'),
     ]),
    ('florencia.rossi', 'Florencia', 'Rossi', '37406921', '341 603-5582',
     None, [
         ('Felipe', PERRO, 'Yorkshire Terrier', 66, '2.9'),
         ('Chloe', GATO, 'Persa', 50, '4.4'),
     ]),
    ('tomas.benedetti', 'Tomás', 'Benedetti', '30587413', '341 571-8046',
     None, [
         ('Rufo', PERRO, 'Mestizo', 120, '22.0'),
     ]),
    ('carla.medina', 'Carla', 'Medina', '41239657', '341 628-3391',
     None, [
         ('Gala', GATO, 'Bengalí', 20, '4.6'),
         ('Lupe', PERRO, 'Shih Tzu', 34, '6.2'),
     ]),
    ('ezequiel.herrera', 'Ezequiel', 'Herrera', '28913075', '341 512-6740',
     None, [
         ('Bobby', PERRO, 'Rottweiler', 44, '42.0'),
         ('Tita', GATO, 'Mestizo', 132, '3.8'),
     ]),
    ('paula.dominguez', 'Paula', 'Domínguez', '38764102', '341 664-0153',
     None, [
         ('Kiwi', GATO, 'Europeo de pelo corto', 28, '4.0'),
     ]),
]

MP = Pago.Metodo.MERCADO_PAGO
EF = Pago.Metodo.EFECTIVO

# Turnos futuros. (dueño, mascota, clase, detalle, motivo, pagar)
#   clase: 'laura' (con la veterinaria de la demo, hoy o mañana),
#   'guardia' (detalle = nivel), 'vacuna' (detalle = vacuna),
#   'atiende' / 'no_atiende' (veterinario que atiende o no la obra
#   social del dueño; detalle = especialidad), 'consulta' (dueño sin
#   obra social).
TURNOS_FUTUROS = [
    ('demo', 'Toby', 'laura', None, 'Control del cachorro', None),
    ('martina.lopez', 'Bruno', 'laura', None, 'Control anual', None),
    ('florencia.rossi', 'Felipe', 'laura', None,
     'Tose desde hace tres días', None),
    ('diego.morales', 'Thor', 'guardia', 'CRITICA',
     'Vómitos con sangre y decaimiento', None),
    ('carla.medina', 'Lupe', 'guardia', 'ALTA',
     'Se golpeó la pata y no la apoya', None),
    ('tomas.benedetti', 'Rufo', 'guardia', 'ALTA',
     'Respira con dificultad', None),
    ('demo', 'Toby', 'vacuna', 'Séxtuple', '', None),
    ('julian.paredes', 'Nala', 'vacuna', 'Triple felina', '', None),
    ('diego.morales', 'Pepa', 'vacuna', 'Séxtuple', '', None),
    ('nicolas.ferrari', 'Mía', 'vacuna', 'Antirrábica', '', None),
    ('sofia.alvarez', 'Kira', 'vacuna', 'Antirrábica', '', None),
    ('paula.dominguez', 'Kiwi', 'vacuna', 'Leucemia felina', '', None),
    ('ezequiel.herrera', 'Bobby', 'vacuna', 'Tos de las perreras', '', None),
    ('lucas.gimenez', 'Simba', 'vacuna', 'Triple felina', '', None),
    ('demo', 'Rocco', 'atiende', _E.CARDIOLOGIA,
     'Le detectaron un soplo en el último control', MP),
    ('demo', 'Mora', 'atiende', _E.CLINICA_GENERAL, 'Control anual', None),
    ('sofia.alvarez', 'Coco', 'atiende', _E.DERMATOLOGIA,
     'Se rasca mucho las orejas', MP),
    ('matias.romero', 'Zeus', 'atiende', _E.TRAUMATOLOGIA,
     'Cojea de la pata trasera', EF),
    ('martina.lopez', 'Bruno', 'atiende', _E.GASTROENTEROLOGIA,
     'Diarrea intermitente', None),
    ('julian.paredes', 'Milo', 'atiende', _E.OFTALMOLOGIA,
     'Lagrimeo en el ojo derecho', None),
    ('camila.suarez', 'Oliver', 'atiende', _E.CLINICA_GENERAL,
     'Bajó de peso', MP),
    ('agustina.ponce', 'Uma', 'atiende', _E.DERMATOLOGIA,
     'Zonas sin pelo en el lomo', None),
    ('lucas.gimenez', 'Lola', 'atiende', _E.CLINICA_GENERAL,
     'Control anual', None),
    ('diego.morales', 'Luna', 'atiende', _E.GASTROENTEROLOGIA,
     'Vomita bolas de pelo seguido', None),
    ('nicolas.ferrari', 'Pancho', 'atiende', _E.CARDIOLOGIA,
     'Control cardiológico por edad', None),
    ('matias.romero', 'Frida', 'atiende', _E.CLINICA_GENERAL,
     'Toma mucha agua', MP),
    ('sofia.alvarez', 'Kira', 'atiende', _E.TRAUMATOLOGIA,
     'Rigidez al levantarse', None),
    ('demo', 'Mora', 'no_atiende', _E.DERMATOLOGIA,
     'Caída de pelo', None),
    ('martina.lopez', 'Bruno', 'no_atiende', _E.OFTALMOLOGIA,
     'Ojos enrojecidos', EF),
    ('camila.suarez', 'Oliver', 'no_atiende', _E.GASTROENTEROLOGIA,
     'Come poco', None),
    ('julian.paredes', 'Milo', 'no_atiende', _E.CLINICA_GENERAL,
     'Estornuda mucho', None),
    ('agustina.ponce', 'Uma', 'no_atiende', _E.TRAUMATOLOGIA,
     'Control de la cadera', None),
    ('diego.morales', 'Thor', 'no_atiende', _E.CARDIOLOGIA,
     'Se cansa rápido en los paseos', None),
    ('florencia.rossi', 'Chloe', 'consulta', _E.DERMATOLOGIA,
     'Caspa y pelo opaco', MP),
    ('tomas.benedetti', 'Rufo', 'consulta', _E.TRAUMATOLOGIA,
     'Dolor en la columna', None),
    ('carla.medina', 'Gala', 'consulta', _E.CLINICA_GENERAL,
     'Control anual', None),
    ('ezequiel.herrera', 'Tita', 'consulta', _E.GASTROENTEROLOGIA,
     'Constipación', None),
    ('ezequiel.herrera', 'Bobby', 'consulta', _E.DERMATOLOGIA,
     'Granitos en la panza', MP),
    ('paula.dominguez', 'Kiwi', 'consulta', _E.OFTALMOLOGIA,
     'Ojo entrecerrado', None),
    ('carla.medina', 'Lupe', 'consulta', _E.CARDIOLOGIA,
     'Control previo a una cirugía', None),
]

# Del dueño principal, para mostrar pagos cancelados y reembolsados:
# (mascota, especialidad, motivo, pagar antes de cancelar)
TURNOS_CANCELADOS_PRINCIPAL = [
    ('Mora', _E.CLINICA_GENERAL, 'Control (lo reprogramo)', False),
    ('Rocco', _E.TRAUMATOLOGIA, 'Revisión de la rodilla', True),
]

# Turnos pasados, FINALIZADOS. (dueño, mascota, clase, detalle, metodo)
#   clase: 'laura', 'consulta' (detalle = especialidad) o 'vacuna'.
TURNOS_PASADOS = [
    ('demo', 'Rocco', 'laura', None, EF),
    ('demo', 'Rocco', 'consulta', _E.CARDIOLOGIA, MP),
    ('demo', 'Mora', 'consulta', _E.CLINICA_GENERAL, MP),
    ('demo', 'Toby', 'vacuna', 'Séxtuple', EF),
    ('martina.lopez', 'Bruno', 'laura', None, EF),
    ('camila.suarez', 'Oliver', 'laura', None, MP),
    ('tomas.benedetti', 'Rufo', 'laura', None, EF),
    ('lucas.gimenez', 'Simba', 'consulta', _E.CLINICA_GENERAL, MP),
    ('lucas.gimenez', 'Lola', 'consulta', _E.DERMATOLOGIA, MP),
    ('julian.paredes', 'Milo', 'consulta', _E.OFTALMOLOGIA, EF),
    ('julian.paredes', 'Nala', 'vacuna', 'Triple felina', EF),
    ('sofia.alvarez', 'Coco', 'consulta', _E.DERMATOLOGIA, MP),
    ('sofia.alvarez', 'Kira', 'consulta', _E.TRAUMATOLOGIA, EF),
    ('diego.morales', 'Thor', 'consulta', _E.CARDIOLOGIA, MP),
    ('diego.morales', 'Pepa', 'vacuna', 'Séxtuple', EF),
    ('diego.morales', 'Luna', 'consulta', _E.GASTROENTEROLOGIA, EF),
    ('matias.romero', 'Zeus', 'consulta', _E.TRAUMATOLOGIA, MP),
    ('matias.romero', 'Frida', 'consulta', _E.CLINICA_GENERAL, EF),
    ('agustina.ponce', 'Uma', 'vacuna', 'Antirrábica', EF),
    ('nicolas.ferrari', 'Pancho', 'consulta', _E.CARDIOLOGIA, MP),
    ('nicolas.ferrari', 'Mía', 'consulta', _E.CLINICA_GENERAL, EF),
    ('florencia.rossi', 'Felipe', 'consulta', _E.GASTROENTEROLOGIA, MP),
    ('florencia.rossi', 'Chloe', 'consulta', _E.OFTALMOLOGIA, EF),
    ('tomas.benedetti', 'Rufo', 'consulta', _E.TRAUMATOLOGIA, EF),
    ('carla.medina', 'Gala', 'vacuna', 'Triple felina', MP),
    ('carla.medina', 'Lupe', 'consulta', _E.DERMATOLOGIA, EF),
    ('ezequiel.herrera', 'Bobby', 'consulta', _E.TRAUMATOLOGIA, MP),
    ('ezequiel.herrera', 'Tita', 'consulta', _E.CLINICA_GENERAL, EF),
    ('paula.dominguez', 'Kiwi', 'consulta', _E.DERMATOLOGIA, EF),
    ('camila.suarez', 'Oliver', 'consulta', _E.GASTROENTEROLOGIA, MP),
]

# Vacunas aplicadas antes de los ultimos 60 dias (ademas de las de los
# turnos pasados de vacunacion): (dueño, mascota, vacuna, hace dias).
VACUNAS_APLICADAS = [
    ('demo', 'Rocco', 'Antirrábica', 300),
    ('demo', 'Rocco', 'Séxtuple', 330),
    ('demo', 'Mora', 'Triple felina', 280),
    ('lucas.gimenez', 'Lola', 'Antirrábica', 250),
    ('martina.lopez', 'Bruno', 'Séxtuple', 340),
    ('sofia.alvarez', 'Coco', 'Tos de las perreras', 200),
    ('diego.morales', 'Thor', 'Antirrábica', 320),
    ('matias.romero', 'Frida', 'Leucemia felina', 210),
    ('nicolas.ferrari', 'Pancho', 'Séxtuple', 290),
    ('florencia.rossi', 'Chloe', 'Triple felina', 260),
    ('ezequiel.herrera', 'Tita', 'Antirrábica', 230),
]

# Entradas de la historia clinica por especialidad (y especie cuando
# cambia). (diagnostico, tratamiento, observaciones)
HISTORIAS = {
    (_E.CLINICA_GENERAL, PERRO): [
        ('Control anual. Buen estado general, mucosas rosadas, '
         'auscultación normal.',
         'Desparasitación interna con praziquantel y pirantel.',
         'Peso estable. Próximo control en 12 meses.'),
        ('Traqueobronquitis leve (tos de las perreras).',
         'Doxiciclina 5 mg/kg cada 12 h por 7 días y antitusivo.',
         'Evitar el contacto con otros perros hasta terminar el '
         'tratamiento.'),
    ],
    (_E.CLINICA_GENERAL, GATO): [
        ('Control anual. Condición corporal 5/9, sin hallazgos.',
         'Desparasitación interna y externa (pipeta).',
         'Se recomienda control de dientes en el próximo turno.'),
        ('Rinotraqueítis leve: estornudos y secreción nasal serosa.',
         'Lisina oral y nebulizaciones con solución fisiológica.',
         'Volver si deja de comer o aparece secreción purulenta.'),
    ],
    (_E.CARDIOLOGIA, PERRO): [
        ('Soplo sistólico grado II/VI en foco mitral. Ecocardiograma '
         'compatible con enfermedad valvular degenerativa estadio B1.',
         'Sin medicación por el momento. Dieta baja en sodio.',
         'Control ecocardiográfico en 6 meses.'),
    ],
    (_E.CARDIOLOGIA, GATO): [
        ('Ecocardiograma sin signos de cardiomiopatía hipertrófica.',
         'No requiere tratamiento.',
         'Control anual por la edad.'),
    ],
    (_E.DERMATOLOGIA, PERRO): [
        ('Otitis externa bilateral por Malassezia.',
         'Limpieza de oídos y gotas óticas con clotrimazol y '
         'gentamicina cada 12 h por 10 días.',
         'Secar bien las orejas después del baño.'),
        ('Dermatitis alérgica por pulgas.',
         'Antiparasitario oral (fluralaner) y antihistamínico por 5 '
         'días.',
         'Tratar también el ambiente y a los otros animales de la casa.'),
    ],
    (_E.DERMATOLOGIA, GATO): [
        ('Dermatofitosis (tiña) en cabeza y orejas.',
         'Itraconazol oral 5 mg/kg por 21 días y baños con champú '
         'antifúngico.',
         'Es contagiosa: lavarse las manos y limpiar mantas y camas.'),
    ],
    (_E.TRAUMATOLOGIA, PERRO): [
        ('Displasia de cadera leve confirmada por radiografía.',
         'Meloxicam 0,1 mg/kg por 7 días y condroprotectores.',
         'Paseos cortos sobre superficies blandas y control de peso.'),
        ('Esguince de carpo derecho.',
         'Reposo, hielo local y antiinflamatorio por 5 días.',
         'Revisar en 10 días si persiste la claudicación.'),
    ],
    (_E.TRAUMATOLOGIA, GATO): [
        ('Contusión en miembro posterior izquierdo tras una caída. '
         'Radiografía sin fracturas.',
         'Robenacoxib por 3 días y reposo en un ambiente reducido.',
         'Evitar que salte a lugares altos por dos semanas.'),
    ],
    (_E.GASTROENTEROLOGIA, PERRO): [
        ('Gastroenteritis aguda por cambio de alimento.',
         'Dieta blanda por 3 días, probióticos y metronidazol.',
         'Volver al alimento habitual de forma gradual.'),
    ],
    (_E.GASTROENTEROLOGIA, GATO): [
        ('Tricobezoares (bolas de pelo) con vómitos frecuentes.',
         'Pasta de malta 3 veces por semana y alimento para control de '
         'bolas de pelo.',
         'Cepillar a diario, sobre todo en época de muda.'),
        ('Constipación leve.',
         'Lactulosa oral y aumento del consumo de agua (fuente o '
         'alimento húmedo).',
         'Controlar la frecuencia de las deposiciones.'),
    ],
    (_E.OFTALMOLOGIA, PERRO): [
        ('Conjuntivitis bacteriana en ojo derecho.',
         'Colirio de tobramicina cada 8 h por 7 días.',
         'Limpiar las secreciones con gasa y solución fisiológica.'),
    ],
    (_E.OFTALMOLOGIA, GATO): [
        ('Úlcera corneal superficial en ojo izquierdo (fluoresceína '
         'positiva).',
         'Colirio antibiótico cada 6 h y collar isabelino.',
         'Control en 5 días para ver la cicatrización.'),
    ],
}


class DatosDemoError(Exception):
    """No se pueden cargar los datos de demo (falta la contraseña o
    algun dato previo)."""


def _ahora():
    return timezone.now()


def _hoy():
    return timezone.localdate()


def duenos_demo():
    return Dueno.objects.filter(email__endswith=DOMINIO)


def hay_datos_demo():
    return duenos_demo().exists()


def veterinario_demo():
    """La veterinaria para mostrar la agenda: la de la cuenta
    laura.fernandez@clinicavet24.com (o, si no tiene cuenta, la de
    matricula MP-5001)."""
    return (
        Veterinario.objects.filter(
            usuario__username=EMAIL_VETERINARIO_DEMO,
        ).first()
        or Veterinario.objects.filter(
            matricula=MATRICULA_VETERINARIO_DEMO,
        ).first()
    )


def _verificar_requisitos():
    """Lanza DatosDemoError si faltan veterinarios, obras sociales o
    vacunas, con el comando que las carga."""
    faltan = []
    activos = Veterinario.objects.filter(estado=Veterinario.Estado.ACTIVO)
    especialidades = set(activos.values_list('especialidad', flat=True))
    requeridas = set(ESPECIALIDADES_CONSULTA) | {_E.VACUNACION, _E.GUARDIA}
    if not requeridas <= especialidades:
        faltan.append(
            'veterinarios de todas las especialidades '
            '(python manage.py cargar_veterinarios)'
        )
    nombres = {d['nombre'] for d in OBRAS_SOCIALES_INICIALES}
    activas = set(
        ObraSocial.objects.filter(nombre__in=nombres, activa=True)
        .values_list('nombre', flat=True)
    )
    if activas != nombres:
        faltan.append(
            'las obras sociales iniciales '
            '(python manage.py cargar_obras_sociales --asignar-veterinarios)'
        )
    elif not activos.filter(obras_sociales__isnull=False).exists():
        faltan.append(
            'veterinarios que atiendan obras sociales '
            '(python manage.py cargar_obras_sociales --asignar-veterinarios)'
        )
    for nombre, especie in VACUNAS_REQUERIDAS:
        if not Vacuna.objects.filter(nombre=nombre, especie=especie).exists():
            faltan.append('las vacunas (python manage.py cargar_vacunas)')
            break
    if veterinario_demo() is None:
        faltan.append(
            f'la veterinaria de la demo ({MATRICULA_VETERINARIO_DEMO})'
        )
    if faltan:
        raise DatosDemoError('Faltan ' + '; '.join(faltan) + '.')


class _Cargador:
    """Arma los datos de demo. Una instancia por carga."""

    def __init__(self, password):
        self.password = password
        self.rng = random.Random(SEMILLA)
        self.duenos = {}
        self.mascotas = {}
        # Dias con turno de cada mascota: no se le dan dos el mismo dia.
        self.dias_ocupados = {}
        self.laura = veterinario_demo()
        self.vacunas = {
            (v.nombre, v.especie): v for v in Vacuna.objects.all()
        }
        self.resumen = {
            'duenos': 0, 'mascotas': 0, 'turnos_futuros': 0,
            'turnos_pasados': 0, 'turnos_cancelados': 0,
            'historias': 0, 'vacunas_aplicadas': 0,
            'turnos_veterinario_demo': 0,
        }

    # -- dueños y mascotas --------------------------------------------

    def cargar_duenos(self):
        obras = {o.nombre: o for o in ObraSocial.objects.all()}
        for usuario, nombre, apellido, dni, telefono, obra, mascotas in (
                DUENOS):
            email = f'{usuario}{DOMINIO}'
            try:
                dueno = registrar_dueno(
                    nombre=nombre, apellido=apellido, dni=dni, email=email,
                    telefono=telefono, password=self.password,
                )
            except RegistroError as error:
                raise DatosDemoError(
                    f'No se pudo registrar a {email}: {error}'
                )
            if obra:
                asignar_obra_social_a_dueno(
                    dueno, obras[obra].pk, f'{dni[-6:]}-{len(usuario):02d}',
                )
            self.duenos[usuario] = dueno
            self.resumen['duenos'] += 1
            for nombre_m, especie, raza, meses, peso in mascotas:
                mascota = registrar_mascota(
                    dueno, nombre_m, especie, raza,
                    self._nacimiento(meses), Decimal(peso),
                )
                self.mascotas[(usuario, nombre_m)] = mascota
                self.dias_ocupados[mascota.pk] = set()
                self.resumen['mascotas'] += 1

    def _nacimiento(self, meses):
        # Dia variado dentro del mes, para que no nazcan todos igual.
        return _hoy() - timedelta(days=meses * 30 + self.rng.randint(0, 25))

    # -- elegir veterinario y horario --------------------------------

    def _veterinarios(self, especialidad, obra_social=None, atiende=None):
        veterinarios = Veterinario.objects.filter(
            especialidad=especialidad, estado=Veterinario.Estado.ACTIVO,
        ).order_by('matricula')
        if obra_social is not None and atiende is not None:
            con_obra = veterinarios.filter(obras_sociales=obra_social)
            veterinarios = (
                con_obra if atiende else veterinarios.exclude(
                    pk__in=con_obra.values('pk'),
                )
            )
        veterinarios = list(veterinarios)
        self.rng.shuffle(veterinarios)
        return veterinarios

    def _horario_libre(self, mascota, veterinario, desde, hasta):
        libres = [
            h for h in turnos_disponibles(
                veterinario_id=veterinario.pk, desde=desde, hasta=hasta,
            )
            if timezone.localtime(h['fecha_hora']).date()
            not in self.dias_ocupados[mascota.pk]
        ]
        return self.rng.choice(libres)['fecha_hora'] if libres else None

    def _veterinario_y_horario(self, mascota, candidatos, desde, hasta):
        for veterinario in candidatos:
            fecha_hora = self._horario_libre(
                mascota, veterinario, desde, hasta,
            )
            if fecha_hora:
                return veterinario, fecha_hora
        return None, None

    def _candidatos(self, dueno, clase, especialidad):
        """Veterinarios para una consulta. Si en la especialidad no hay
        ninguno que atienda (o no atienda) la obra social, se busca en
        las otras especialidades de consulta."""
        if clase in ('atiende', 'no_atiende') and dueno.obra_social:
            atiende = clase == 'atiende'
            orden = [especialidad] + [
                e for e in ESPECIALIDADES_CONSULTA if e != especialidad
            ]
            for opcion in orden:
                candidatos = self._veterinarios(
                    opcion, dueno.obra_social, atiende,
                )
                if candidatos:
                    return candidatos
        return self._veterinarios(especialidad)

    # -- turnos futuros ----------------------------------------------

    def _marcar(self, turno, mascota):
        self.dias_ocupados[mascota.pk].add(
            timezone.localtime(turno.fecha_hora).date()
        )

    def _pagar(self, turno, metodo, cuando=None):
        pago = turno.pagos.get()
        if pago.estado != Pago.Estado.PENDIENTE:
            return pago
        marcar_pagado(pago, metodo)
        if metodo == MP:
            pago.mp_payment_id = f'DEMO-{pago.pk}'
        pago.fecha_pago = cuando or _ahora()
        pago.save(update_fields=['mp_payment_id', 'fecha_pago'])
        return pago

    def _reservar_laura(self, dueno, mascota, motivo):
        """Con la veterinaria de la demo, hoy o mañana; si ya no le
        quedan horarios esos dias, el proximo que tenga."""
        ahora = _ahora()
        fin_de_manana = timezone.make_aware(
            datetime.combine(_hoy() + timedelta(days=2), datetime.min.time())
        )
        for hasta in (fin_de_manana, ahora + timedelta(days=DIAS_FUTURO)):
            fecha_hora = self._horario_libre(
                mascota, self.laura, ahora, hasta,
            )
            if fecha_hora:
                return reservar_turno(
                    dueno, mascota.pk, self.laura.pk, fecha_hora,
                    motivo=motivo,
                )
        return None

    def cargar_turnos_futuros(self):
        ahora = _ahora()
        manana = ahora + timedelta(days=1)
        hasta = ahora + timedelta(days=DIAS_FUTURO)
        for usuario, nombre, clase, detalle, motivo, pagar in (
                TURNOS_FUTUROS):
            dueno = self.duenos[usuario]
            mascota = self.mascotas[(usuario, nombre)]
            turno = None
            if clase == 'laura':
                turno = self._reservar_laura(dueno, mascota, motivo)
                if turno:
                    self.resumen['turnos_veterinario_demo'] += 1
            elif clase == 'guardia':
                # Una urgencia es para ya: el primer dia.
                veterinario, fecha_hora = self._veterinario_y_horario(
                    mascota, self._veterinarios(_E.GUARDIA), ahora,
                    ahora + timedelta(days=1),
                )
                if veterinario:
                    turno = reservar_turno(
                        dueno, mascota.pk, veterinario.pk, fecha_hora,
                        nivel_urgencia=detalle, motivo=motivo,
                        tipo=TIPO_GUARDIA,
                    )
            elif clase == 'vacuna':
                vacuna = self.vacunas[(detalle, mascota.especie)]
                veterinario, fecha_hora = self._veterinario_y_horario(
                    mascota, self._veterinarios(_E.VACUNACION), manana,
                    hasta,
                )
                if veterinario:
                    turno = reservar_turno_vacuna(
                        dueno, mascota.pk, vacuna.pk, veterinario.pk,
                        fecha_hora,
                    )
            else:
                veterinario, fecha_hora = self._veterinario_y_horario(
                    mascota, self._candidatos(dueno, clase, detalle),
                    manana, hasta,
                )
                if veterinario:
                    turno = reservar_turno(
                        dueno, mascota.pk, veterinario.pk, fecha_hora,
                        motivo=motivo, tipo=TIPO_CONSULTA,
                    )
            if turno is None:
                continue
            self._marcar(turno, mascota)
            self.resumen['turnos_futuros'] += 1
            if pagar:
                self._pagar(turno, pagar)

        # Del dueño principal: uno cancelado y uno pagado y cancelado.
        principal = self.duenos['demo']
        for nombre, especialidad, motivo, pagar in (
                TURNOS_CANCELADOS_PRINCIPAL):
            mascota = self.mascotas[('demo', nombre)]
            veterinario, fecha_hora = self._veterinario_y_horario(
                mascota, self._veterinarios(especialidad),
                ahora + timedelta(days=2), hasta,
            )
            if veterinario is None:
                continue
            turno = reservar_turno(
                principal, mascota.pk, veterinario.pk, fecha_hora,
                motivo=motivo, tipo=TIPO_CONSULTA,
            )
            if pagar:
                self._pagar(turno, MP)
            cancelar_turno(principal, turno.pk)
            self.resumen['turnos_cancelados'] += 1

    # -- turnos pasados ----------------------------------------------

    def _horario_pasado(self, mascota, veterinario):
        """Un comienzo de turno de los ultimos 60 dias dentro del horario
        del veterinario, libre y sin otro turno de la mascota ese dia."""
        dias = list(range(1, DIAS_PASADO + 1))
        self.rng.shuffle(dias)
        for hace in dias:
            dia = _hoy() - timedelta(days=hace)
            if dia in self.dias_ocupados[mascota.pk]:
                continue
            comienzos = horarios_del_dia(veterinario, dia)
            ocupados = set(
                Turno.objects.filter(
                    veterinario=veterinario,
                    fecha_hora__in=comienzos,
                ).exclude(estado=Turno.Estado.CANCELADO)
                .values_list('fecha_hora', flat=True)
            )
            libres = [
                c for c in comienzos
                if c not in ocupados and c < _ahora()
            ]
            if libres:
                return self.rng.choice(libres)
        return None

    def _nivel_baja(self):
        return (
            NivelUrgencia.objects.filter(
                nivel_urgencia=NivelUrgencia.Nivel.BAJA,
            ).order_by('id').first()
            or NivelUrgencia.objects.create(
                nivel_urgencia=NivelUrgencia.Nivel.BAJA,
                sintomas_descripcion='',
            )
        )

    def _texto_historia(self, especialidad, mascota, vacuna=None):
        if vacuna is not None:
            return (
                f'Aplicación de vacuna {vacuna.nombre}. Examen previo '
                'normal, temperatura dentro de los valores de referencia.',
                f'Vacuna {vacuna.nombre} por vía subcutánea.',
                'Puede presentar decaimiento leve por 24 h. Próxima dosis '
                'según el calendario de vacunación.',
            )
        return self.rng.choice(HISTORIAS[(especialidad, mascota.especie)])

    def cargar_turnos_pasados(self):
        nivel = self._nivel_baja()
        for usuario, nombre, clase, detalle, metodo in TURNOS_PASADOS:
            mascota = self.mascotas[(usuario, nombre)]
            vacuna = None
            if clase == 'laura':
                candidatos = [self.laura]
            elif clase == 'vacuna':
                vacuna = self.vacunas[(detalle, mascota.especie)]
                candidatos = self._veterinarios(_E.VACUNACION)
            else:
                candidatos = self._veterinarios(detalle)
            veterinario = fecha_hora = None
            for candidato in candidatos:
                fecha_hora = self._horario_pasado(mascota, candidato)
                if fecha_hora:
                    veterinario = candidato
                    break
            if veterinario is None:
                continue
            # Un cachorro no se vacuna antes de los 2 meses.
            if vacuna and (
                fecha_hora.date() - mascota.fecha_nacimiento
            ).days < 60:
                continue

            turno = Turno.objects.create(
                mascota=mascota,
                veterinario=veterinario,
                nivel_urgencia=nivel,
                vacuna=vacuna,
                fecha_hora=fecha_hora,
                tipo=TIPO_VACUNACION if vacuna else TIPO_CONSULTA,
                estado=Turno.Estado.FINALIZADO,
            )
            self._marcar(turno, mascota)
            crear_pago_de_turno(turno)
            atendido = fecha_hora + timedelta(minutes=30)
            self._pagar(turno, metodo, cuando=atendido)

            diagnostico, tratamiento, observaciones = self._texto_historia(
                veterinario.especialidad, mascota, vacuna,
            )
            entrada = HistorialClinico.objects.create(
                mascota=mascota, veterinario=veterinario, turno=turno,
                diagnostico=diagnostico, tratamiento=tratamiento,
                observaciones=observaciones,
            )
            # fecha es auto_now_add: se lleva al momento de la atencion.
            HistorialClinico.objects.filter(pk=entrada.pk).update(
                fecha=atendido,
            )
            if vacuna:
                AplicacionVacuna.objects.create(
                    mascota=mascota, vacuna=vacuna,
                    fecha_aplicacion=timezone.localtime(fecha_hora).date(),
                )
                self.resumen['vacunas_aplicadas'] += 1
            if veterinario == self.laura:
                self.resumen['turnos_veterinario_demo'] += 1
            self.resumen['turnos_pasados'] += 1
            self.resumen['historias'] += 1

    def cargar_vacunas_aplicadas(self):
        for usuario, nombre, vacuna_nombre, hace in VACUNAS_APLICADAS:
            mascota = self.mascotas[(usuario, nombre)]
            fecha = _hoy() - timedelta(days=hace)
            if (fecha - mascota.fecha_nacimiento).days < 60:
                continue
            AplicacionVacuna.objects.create(
                mascota=mascota,
                vacuna=self.vacunas[(vacuna_nombre, mascota.especie)],
                fecha_aplicacion=fecha,
            )
            self.resumen['vacunas_aplicadas'] += 1


def _pagos_por_estado():
    pagos = Pago.objects.filter(turno__mascota__dueno__email__endswith=DOMINIO)
    return {
        estado.label: pagos.filter(estado=estado.value).count()
        for estado in Pago.Estado
    }


def cargar_datos_demo(password):
    """Carga los datos de demo. Devuelve el resumen; si ya estaban
    cargados no hace nada (resumen con 'ya_cargados': True). Lanza
    DatosDemoError si falta la contraseña o algun dato previo."""
    if not password:
        raise DatosDemoError(
            'Falta la contraseña de los dueños de demo: definí '
            'DEMO_PASSWORD en el .env.'
        )
    if hay_datos_demo():
        return {
            'ya_cargados': True,
            'duenos': duenos_demo().count(),
            **_datos_de_acceso(),
        }
    _verificar_requisitos()
    with transaction.atomic():
        cargador = _Cargador(password)
        cargador.cargar_duenos()
        cargador.cargar_turnos_pasados()
        cargador.cargar_vacunas_aplicadas()
        cargador.cargar_turnos_futuros()
    return {
        'ya_cargados': False,
        **cargador.resumen,
        'pagos': _pagos_por_estado(),
        **_datos_de_acceso(),
    }


def _datos_de_acceso():
    laura = veterinario_demo()
    return {
        'email_principal': EMAIL_PRINCIPAL,
        'email_veterinario': (
            laura.usuario.email if laura and laura.usuario_id else None
        ),
        'nombre_veterinario': laura.nombre if laura else None,
    }


def borrar_datos_demo():
    """Borra los dueños @demo.clinicavet24.com con sus cuentas,
    mascotas, turnos, pagos, historias y vacunas aplicadas (todo cae en
    cascada desde la cuenta). No toca nada mas. Devuelve lo borrado."""
    duenos = duenos_demo()
    turnos = Turno.objects.filter(mascota__dueno__in=duenos)
    borrado = {
        'duenos': duenos.count(),
        'mascotas': Mascota.objects.filter(dueno__in=duenos).count(),
        'turnos': turnos.count(),
        'pagos': Pago.objects.filter(turno__in=turnos).count(),
        'historias': HistorialClinico.objects.filter(
            mascota__dueno__in=duenos,
        ).count(),
    }
    User = get_user_model()
    with transaction.atomic():
        User.objects.filter(username__endswith=DOMINIO).delete()
    return borrado
