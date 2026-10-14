import warnings
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from administracion.models import Pago
from atencion.models import HorarioAtencion, NivelUrgencia, Turno, Veterinario
from atencion.services.turnos import (
    PRECIO_POR_ESPECIALIDAD,
    HorarioNoDisponible,
    SeleccionInvalida,
    TurnoError,
    TurnoNoEncontrado,
    cancelar_turno,
    crear_turno_manual,
    especialidades_para_turno,
    horario_para_consulta,
    obtener_especialidad_para_turno,
    obtener_turnos_disponibles,
    puede_cancelarse,
    reservar_turno,
    reservar_turno_de_consulta,
    semana_de_turnos,
    turnos_disponibles,
)
from clinica.services.mascotas import dar_de_baja_mascota, registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

ZONA = ZoneInfo('America/Argentina/Buenos_Aires')
# Miercoles 14/10/2026 a las 12:00 (hora de Argentina).
AHORA = datetime(2026, 10, 14, 12, 0, tzinfo=ZONA)
# Jueves 15/10/2026 a las 10:00: un horario valido del clinico.
MANANA_10 = datetime(2026, 10, 15, 10, 0, tzinfo=ZONA)


def crear_veterinario(nombre, matricula, especialidad, inicio, fin,
                      estado='ACTIVO', dias=range(6)):
    """Veterinario con horario de lunes a sabado (o los `dias` dados)."""
    veterinario = Veterinario.objects.create(
        nombre=nombre, matricula=matricula, especialidad=especialidad,
        estado=estado,
    )
    HorarioAtencion.objects.bulk_create([
        HorarioAtencion(
            veterinario=veterinario, dia_semana=dia,
            hora_inicio=inicio, hora_fin=fin,
        )
        for dia in dias
    ])
    return veterinario


class TurnosBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.clinico = crear_veterinario(
            'Dra. Laura Fernández', 'MP-5001', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )
        cls.cardiologo = crear_veterinario(
            'Dr. Federico Acosta', 'MP-5004', 'CARDIOLOGIA',
            time(13, 0), time(19, 0),
        )
        cls.ana = crear_dueno()
        cls.firulais = registrar_mascota(cls.ana, **datos_mascota())
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.michi = registrar_mascota(
            cls.beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        parche = patch('django.utils.timezone.now', return_value=AHORA)
        parche.start()
        self.addCleanup(parche.stop)

    def reservar(self, **cambios):
        argumentos = {
            'dueno': self.ana,
            'mascota_id': self.firulais.pk,
            'veterinario_id': self.clinico.pk,
            'fecha_hora': MANANA_10,
        }
        argumentos.update(cambios)
        return reservar_turno(**argumentos)


class ReservarTurnoTests(TurnosBase):

    def test_crea_el_turno_y_exactamente_un_pago_pendiente(self):
        turno = self.reservar(motivo='Control anual')

        turno.refresh_from_db()
        self.assertEqual(turno.mascota, self.firulais)
        self.assertEqual(turno.veterinario, self.clinico)
        self.assertEqual(turno.fecha_hora, MANANA_10)
        self.assertEqual(turno.estado, Turno.Estado.PENDIENTE)
        self.assertEqual(turno.tipo, 'Consulta Regular')
        self.assertEqual(turno.motivo, 'Control anual')
        self.assertIsNone(turno.vacuna)
        pago = Pago.objects.get()
        self.assertEqual(pago.turno, turno)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)
        self.assertEqual(pago.monto_total, Decimal('15000'))
        self.assertEqual(pago.monto_cubierto_os, Decimal('0'))
        self.assertEqual(pago.metodo, '')

    def test_el_precio_es_el_de_la_especialidad_del_veterinario(self):
        turno = self.reservar(
            veterinario_id=self.cardiologo.pk,
            fecha_hora=MANANA_10.replace(hour=15),
        )

        self.assertEqual(
            turno.pagos.get().monto_total,
            PRECIO_POR_ESPECIALIDAD[Veterinario.Especialidad.CARDIOLOGIA],
        )
        self.assertEqual(turno.pagos.get().monto_total, Decimal('28000'))

    def test_sin_nivel_de_urgencia_usa_baja_y_la_crea_si_falta(self):
        self.assertFalse(NivelUrgencia.objects.exists())

        turno = self.reservar()
        otro = self.reservar(fecha_hora=MANANA_10.replace(hour=11))

        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'BAJA')
        self.assertEqual(otro.nivel_urgencia, turno.nivel_urgencia)
        self.assertEqual(NivelUrgencia.objects.count(), 1)

    def test_acepta_el_nivel_de_urgencia_y_la_fecha_como_texto(self):
        turno = self.reservar(
            nivel_urgencia='ALTA', fecha_hora=MANANA_10.isoformat(),
            tipo='Triage',
        )

        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'ALTA')
        self.assertEqual(turno.fecha_hora, MANANA_10)
        self.assertEqual(turno.tipo, 'Triage')

    def test_doble_reserva_del_mismo_horario_no_duplica(self):
        self.reservar()

        with self.assertRaises(HorarioNoDisponible) as ctx:
            self.reservar(dueno=self.beto, mascota_id=self.michi.pk)

        self.assertIn('acaba de ser reservado', str(ctx.exception))
        self.assertEqual(Turno.objects.count(), 1)
        self.assertEqual(Pago.objects.count(), 1)

    def test_reserva_simultanea_la_frena_la_restriccion_de_la_base(self):
        # Simula la carrera: la verificacion "sigue libre" no ve el
        # turno del otro dueño y la restriccion de unicidad lo rechaza.
        self.reservar()

        with patch('django.db.models.query.QuerySet.exists',
                   return_value=False):
            with self.assertRaises(HorarioNoDisponible):
                self.reservar(dueno=self.beto, mascota_id=self.michi.pk)

        self.assertEqual(Turno.objects.count(), 1)
        self.assertEqual(Pago.objects.count(), 1)

    def test_la_base_no_admite_dos_turnos_activos_iguales(self):
        turno = self.reservar()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Turno.objects.create(
                    mascota=self.michi, veterinario=self.clinico,
                    nivel_urgencia=turno.nivel_urgencia,
                    fecha_hora=MANANA_10, tipo='Consulta Regular',
                )

    def test_mismo_horario_con_otro_veterinario_esta_permitido(self):
        self.reservar(fecha_hora=MANANA_10.replace(hour=15))

        otro = self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
            veterinario_id=self.cardiologo.pk,
            fecha_hora=MANANA_10.replace(hour=15),
        )

        self.assertEqual(otro.veterinario, self.cardiologo)

    def test_mascota_de_otro_dueno_da_error(self):
        with self.assertRaises(TurnoError):
            self.reservar(mascota_id=self.michi.pk)

        self.assertEqual(Turno.objects.count(), 0)
        self.assertEqual(Pago.objects.count(), 0)

    def test_mascota_dada_de_baja_da_error(self):
        dar_de_baja_mascota(self.ana, self.firulais.pk)

        with self.assertRaises(TurnoError):
            self.reservar()

    def test_personal_sin_dueno_no_puede_reservar(self):
        with self.assertRaises(TurnoError):
            self.reservar(dueno=None)

    def test_horario_fuera_del_horario_de_atencion_da_error(self):
        fuera = {
            'antes de abrir': MANANA_10.replace(hour=7, minute=30),
            'al cierre': MANANA_10.replace(hour=19),
            'fuera de la grilla': MANANA_10.replace(minute=15),
            'domingo': datetime(2026, 10, 18, 10, 0, tzinfo=ZONA),
            'cardiologo de mañana': MANANA_10,
        }
        for caso, fecha_hora in fuera.items():
            with self.subTest(caso=caso):
                veterinario = (
                    self.cardiologo if 'cardiologo' in caso else self.clinico
                )
                with self.assertRaises(TurnoError) as ctx:
                    self.reservar(
                        veterinario_id=veterinario.pk, fecha_hora=fecha_hora,
                    )
                self.assertIn('no atiende en ese horario', str(ctx.exception))
        self.assertEqual(Turno.objects.count(), 0)

    def test_el_ultimo_turno_del_dia_es_valido(self):
        turno = self.reservar(fecha_hora=MANANA_10.replace(hour=18, minute=30))

        self.assertIsNotNone(turno.pk)

    def test_horario_pasado_o_invalido_da_error(self):
        for fecha_hora in (AHORA - timedelta(hours=2), AHORA, 'mañana', None):
            with self.subTest(fecha_hora=fecha_hora):
                with self.assertRaises(TurnoError):
                    self.reservar(fecha_hora=fecha_hora)
        self.assertEqual(Turno.objects.count(), 0)

    def test_veterinario_inactivo_o_inexistente_da_error(self):
        inactivo = crear_veterinario(
            'Dr. Inactivo', 'MP-9999', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0), estado='INACTIVO',
        )

        for veterinario_id in (inactivo.pk, 999999, 'abc'):
            with self.subTest(veterinario_id=veterinario_id):
                with self.assertRaises(TurnoError):
                    self.reservar(veterinario_id=veterinario_id)


class CancelarTurnoTests(TurnosBase):

    def test_cancelar_libera_el_horario_y_cancela_el_pago(self):
        turno = self.reservar()

        cancelar_turno(self.ana, turno.pk)

        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.CANCELADO)
        self.assertEqual(turno.pagos.get().estado, Pago.Estado.CANCELADO)
        libres = turnos_disponibles(veterinario_id=self.clinico.pk)
        self.assertIn(MANANA_10, [h['fecha_hora'] for h in libres])
        nuevo = self.reservar(dueno=self.beto, mascota_id=self.michi.pk)
        self.assertEqual(nuevo.fecha_hora, MANANA_10)
        self.assertEqual(nuevo.pagos.get().estado, Pago.Estado.PENDIENTE)

    def test_con_dos_horas_o_menos_de_anticipacion_da_error(self):
        for hora, minuto in ((13, 0), (14, 0)):
            with self.subTest(hora=hora):
                turno = self.reservar(
                    fecha_hora=AHORA.replace(hour=hora, minute=minuto),
                )

                self.assertFalse(puede_cancelarse(turno))
                with self.assertRaises(TurnoError) as ctx:
                    cancelar_turno(self.ana, turno.pk)

                self.assertIn('2 horas antes', str(ctx.exception))
                turno.refresh_from_db()
                self.assertEqual(turno.estado, Turno.Estado.PENDIENTE)
                self.assertEqual(
                    turno.pagos.get().estado, Pago.Estado.PENDIENTE,
                )

    def test_con_mas_de_dos_horas_se_puede(self):
        turno = self.reservar(fecha_hora=AHORA.replace(hour=14, minute=30))

        self.assertTrue(puede_cancelarse(turno))
        cancelar_turno(self.ana, turno.pk)

        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.CANCELADO)

    def test_turno_de_otro_dueno_no_se_encuentra(self):
        turno = self.reservar()

        with self.assertRaises(TurnoNoEncontrado):
            cancelar_turno(self.beto, turno.pk)

        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.PENDIENTE)

    def test_no_se_puede_cancelar_un_turno_pasado_o_ya_cancelado(self):
        pasado = Turno.objects.create(
            mascota=self.firulais, veterinario=self.clinico,
            nivel_urgencia=NivelUrgencia.objects.create(
                nivel_urgencia='BAJA', sintomas_descripcion='',
            ),
            fecha_hora=AHORA - timedelta(days=1), tipo='Consulta Regular',
        )
        cancelado = self.reservar()
        cancelar_turno(self.ana, cancelado.pk)

        for turno in (pasado, cancelado):
            with self.subTest(turno=turno.pk):
                with self.assertRaises(TurnoError):
                    cancelar_turno(self.ana, turno.pk)


class TurnosDisponiblesTests(TurnosBase):

    def test_solo_horarios_futuros_dentro_del_horario_de_atencion(self):
        hasta = AHORA.replace(hour=23)

        libres = turnos_disponibles(
            veterinario_id=self.clinico.pk, hasta=hasta,
        )

        horas = [h['fecha_hora'] for h in libres]
        # A las 12:00 en punto, el turno de las 12:00 ya no se ofrece.
        self.assertEqual(horas[0], AHORA.replace(minute=30))
        self.assertEqual(horas[-1], AHORA.replace(hour=18, minute=30))
        self.assertEqual(len(horas), 13)

    def test_un_dia_completo_tiene_22_turnos_y_el_domingo_ninguno(self):
        jueves = turnos_disponibles(
            veterinario_id=self.clinico.pk,
            desde=datetime(2026, 10, 15, 0, 0, tzinfo=ZONA),
            hasta=datetime(2026, 10, 15, 23, 59, tzinfo=ZONA),
        )
        domingo = turnos_disponibles(
            desde=datetime(2026, 10, 18, 0, 0, tzinfo=ZONA),
            hasta=datetime(2026, 10, 18, 23, 59, tzinfo=ZONA),
        )

        self.assertEqual(len(jueves), 22)
        self.assertEqual(jueves[0]['fecha_hora'], MANANA_10.replace(hour=8))
        self.assertEqual(domingo, [])

    def test_filtra_por_especialidad_y_por_veterinario(self):
        por_especialidad = turnos_disponibles(especialidad='CARDIOLOGIA')
        por_veterinario = turnos_disponibles(veterinario_id=self.clinico.pk)
        todos = turnos_disponibles()

        self.assertEqual(
            {h['veterinario_id'] for h in por_especialidad},
            {self.cardiologo.pk},
        )
        self.assertEqual(
            {h['veterinario_id'] for h in por_veterinario},
            {self.clinico.pk},
        )
        self.assertEqual(
            len(todos), len(por_especialidad) + len(por_veterinario),
        )
        self.assertEqual(
            todos, sorted(todos, key=lambda h: h['fecha_hora']),
        )

    def test_no_devuelve_ocupados_ni_veterinarios_inactivos(self):
        self.reservar()
        crear_veterinario(
            'Dr. Inactivo', 'MP-9999', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0), estado='INACTIVO',
        )

        libres = turnos_disponibles(especialidad='CLINICA_GENERAL')

        self.assertNotIn(MANANA_10, [h['fecha_hora'] for h in libres])
        self.assertEqual(
            {h['veterinario_nombre'] for h in libres},
            {'Dra. Laura Fernández'},
        )

    def test_hace_dos_consultas_sin_importar_cuantos_dias(self):
        with self.assertNumQueries(2):
            turnos_disponibles(hasta=AHORA + timedelta(days=14))


class AliasObsoletosTests(TurnosBase):

    def test_crear_turno_manual_delega_en_reservar_turno(self):
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter('always')
            turno = crear_turno_manual(
                mascota_id=self.firulais.pk, nivel_urgencia_str='MEDIA',
                tipo='Consulta Regular', veterinario_id=self.clinico.pk,
                fecha_hora=MANANA_10.isoformat(),
            )

        self.assertTrue(
            any(a.category is DeprecationWarning for a in avisos)
        )
        self.assertEqual(turno.mascota, self.firulais)
        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'MEDIA')
        self.assertEqual(turno.pagos.count(), 1)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with self.assertRaises(TurnoError):
                crear_turno_manual(
                    self.michi.pk, 'MEDIA', 'Consulta Regular',
                    self.clinico.pk, MANANA_10,
                )

    def test_obtener_turnos_disponibles_sigue_funcionando(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            viejos = obtener_turnos_disponibles(dias_adelante=3)

        self.assertEqual(
            viejos, turnos_disponibles(hasta=AHORA + timedelta(days=3)),
        )


class GuardiaYFinDelDiaTests(TurnosBase):
    """Franjas de guardia: los 7 dias y hasta el final del dia (el
    campo no admite 24:00, se carga 23:59)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.de_noche = crear_veterinario(
            'Dr. Cristian Maldonado', 'MP-5026', 'GUARDIA',
            time(16, 0), time(23, 59), dias=range(7),
        )
        cls.de_madrugada = crear_veterinario(
            'Dr. Hernán Quiroga', 'MP-5022', 'GUARDIA',
            time(0, 0), time(8, 0), dias=range(7),
        )

    def test_hay_turnos_de_guardia_un_domingo_a_las_3_de_la_madrugada(self):
        domingo_3 = datetime(2026, 10, 18, 3, 0, tzinfo=ZONA)

        libres = turnos_disponibles(
            especialidad='GUARDIA',
            desde=domingo_3 - timedelta(minutes=1),
            hasta=domingo_3,
        )

        self.assertEqual(
            [(h['fecha_hora'], h['veterinario_id']) for h in libres],
            [(domingo_3, self.de_madrugada.pk)],
        )

    def test_la_franja_hasta_23_59_incluye_el_turno_de_las_23_30(self):
        hoy_noche = turnos_disponibles(
            veterinario_id=self.de_noche.pk, hasta=AHORA.replace(hour=23),
        )
        todo_el_dia = turnos_disponibles(
            veterinario_id=self.de_noche.pk,
            hasta=AHORA.replace(hour=23, minute=59),
        )

        self.assertEqual(hoy_noche[0]['fecha_hora'], AHORA.replace(hour=16))
        self.assertEqual(
            todo_el_dia[-1]['fecha_hora'], AHORA.replace(hour=23, minute=30),
        )
        self.assertEqual(len(todo_el_dia), 16)

    def test_se_puede_reservar_a_las_23_30_y_un_domingo_de_madrugada(self):
        ultimo = self.reservar(
            veterinario_id=self.de_noche.pk,
            fecha_hora=AHORA.replace(hour=23, minute=30),
            tipo='Guardia',
        )
        domingo = self.reservar(
            veterinario_id=self.de_madrugada.pk,
            fecha_hora=datetime(2026, 10, 18, 3, 0, tzinfo=ZONA),
            tipo='Guardia',
        )

        self.assertEqual(ultimo.pagos.get().monto_total, Decimal('30000'))
        self.assertEqual(domingo.tipo, 'Guardia')
        with self.assertRaises(TurnoError):
            self.reservar(
                veterinario_id=self.de_noche.pk,
                fecha_hora=AHORA.replace(hour=23, minute=45),
            )


class SacarTurnoServiceTests(TurnosBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.otro_clinico = crear_veterinario(
            'Dr. Martín Sosa', 'MP-5002', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )
        cls.guardia = crear_veterinario(
            'Dra. Luciana Paz', 'MP-5025', 'GUARDIA',
            time(8, 0), time(16, 0), dias=range(7),
        )
        crear_veterinario(
            'Dra. Paula Navarro', 'MP-5019', 'VACUNACION',
            time(8, 0), time(13, 0),
        )
        crear_veterinario(
            'Dr. Inactivo', 'MP-9999', 'DERMATOLOGIA',
            time(8, 0), time(19, 0), estado='INACTIVO',
        )

    def test_especialidades_excluye_guardia_vacunacion_y_sin_activos(self):
        especialidades = especialidades_para_turno()

        self.assertEqual(
            [e['codigo'] for e in especialidades],
            ['CLINICA_GENERAL', 'CARDIOLOGIA'],
        )
        self.assertEqual(especialidades[0]['nombre'], 'Clínica general')
        self.assertEqual(especialidades[0]['precio'], Decimal('15000'))
        self.assertTrue(especialidades[0]['descripcion'])

    def test_especialidad_no_ofrecida_es_invalida(self):
        for codigo in ('GUARDIA', 'VACUNACION', 'DERMATOLOGIA', 'XX', None):
            with self.subTest(codigo=codigo):
                with self.assertRaises(SeleccionInvalida):
                    obtener_especialidad_para_turno(codigo)

    def test_semana_actual_va_de_lunes_a_sabado_con_los_libres(self):
        semana = semana_de_turnos('CARDIOLOGIA')

        self.assertEqual(semana['lunes'], date(2026, 10, 12))
        self.assertEqual(
            [d['fecha'].day for d in semana['dias']],
            [12, 13, 14, 15, 16, 17],
        )
        lunes, martes, miercoles, jueves = semana['dias'][:4]
        self.assertEqual(lunes['horarios'], [])
        self.assertEqual(martes['horarios'], [])
        self.assertTrue(miercoles['es_hoy'])
        self.assertEqual(
            miercoles['horarios'][0]['fecha_hora'], AHORA.replace(hour=13),
        )
        self.assertEqual(len(jueves['horarios']), 12)
        self.assertEqual(
            {h['veterinario_id'] for d in semana['dias']
             for h in d['horarios']},
            {self.cardiologo.pk},
        )
        self.assertEqual(
            jueves['horarios'][0]['veterinario_apellido'], 'Acosta',
        )
        self.assertIsNone(semana['semana_anterior'])
        self.assertEqual(semana['semana_siguiente'], '2026-10-19')

    def test_con_todos_ofrece_un_horario_por_hora(self):
        semana = semana_de_turnos('CLINICA_GENERAL')

        jueves = semana['dias'][3]
        horas = [h['fecha_hora'] for h in jueves['horarios']]
        self.assertEqual(len(horas), 22)
        self.assertEqual(len(set(horas)), 22)
        self.assertEqual(
            [v.nombre for v in semana['veterinarios']],
            ['Dr. Martín Sosa', 'Dra. Laura Fernández'],
        )
        self.assertIsNone(semana['veterinario'])

    def test_filtra_por_veterinario_y_saca_los_ocupados(self):
        self.reservar()

        semana = semana_de_turnos(
            'CLINICA_GENERAL', veterinario_id=self.clinico.pk,
        )

        jueves = semana['dias'][3]
        self.assertEqual(semana['veterinario'], self.clinico)
        self.assertEqual(len(jueves['horarios']), 21)
        self.assertNotIn(
            MANANA_10, [h['fecha_hora'] for h in jueves['horarios']],
        )
        self.assertEqual(
            {h['veterinario_id'] for h in jueves['horarios']},
            {self.clinico.pk},
        )

    def test_veterinario_de_otra_especialidad_es_invalido(self):
        with self.assertRaises(SeleccionInvalida):
            semana_de_turnos(
                'CLINICA_GENERAL', veterinario_id=self.cardiologo.pk,
            )

    def test_no_se_puede_ir_a_semanas_pasadas(self):
        pasada = semana_de_turnos('CARDIOLOGIA', semana='2026-09-01')
        siguiente = semana_de_turnos('CARDIOLOGIA', semana='2026-10-21')
        invalida = semana_de_turnos('CARDIOLOGIA', semana='cualquiera')
        muy_lejos = semana_de_turnos('CARDIOLOGIA', semana='2030-01-01')

        self.assertEqual(pasada['lunes'], date(2026, 10, 12))
        self.assertEqual(invalida['lunes'], date(2026, 10, 12))
        self.assertEqual(siguiente['lunes'], date(2026, 10, 19))
        self.assertEqual(siguiente['semana_anterior'], '2026-10-12')
        self.assertEqual(len(siguiente['dias'][0]['horarios']), 12)
        self.assertEqual(muy_lejos['lunes'], date(2026, 12, 7))
        self.assertIsNone(muy_lejos['semana_siguiente'])

    def test_horario_para_consulta_devuelve_los_datos_y_el_precio(self):
        horario = horario_para_consulta(
            'CARDIOLOGIA', self.cardiologo.pk,
            MANANA_10.replace(hour=15).isoformat(),
        )

        self.assertEqual(horario['veterinario'], self.cardiologo)
        self.assertEqual(horario['fecha_hora'], MANANA_10.replace(hour=15))
        self.assertEqual(horario['precio'], Decimal('28000'))
        self.assertEqual(horario['especialidad']['nombre'], 'Cardiología')

    def test_horario_para_consulta_ocupado_o_fuera_de_horario(self):
        self.reservar()

        for fecha_hora in (MANANA_10, MANANA_10.replace(hour=20)):
            with self.subTest(fecha_hora=fecha_hora):
                with self.assertRaises(HorarioNoDisponible):
                    horario_para_consulta(
                        'CLINICA_GENERAL', self.clinico.pk, fecha_hora,
                    )

    def test_reservar_turno_de_consulta_crea_turno_con_motivo_y_pago(self):
        turno = reservar_turno_de_consulta(
            self.ana, self.firulais.pk, 'CLINICA_GENERAL', self.clinico.pk,
            MANANA_10, motivo='Control anual',
        )

        self.assertEqual(turno.tipo, 'Consulta Regular')
        self.assertEqual(turno.motivo, 'Control anual')
        self.assertEqual(turno.pagos.get().monto_total, Decimal('15000'))

    def test_no_se_reserva_consulta_con_guardia_ni_cruzando_veterinario(
        self,
    ):
        casos = (
            ('GUARDIA', self.guardia.pk),
            ('CLINICA_GENERAL', self.guardia.pk),
            ('CARDIOLOGIA', self.clinico.pk),
        )
        for especialidad, veterinario_id in casos:
            with self.subTest(especialidad=especialidad):
                with self.assertRaises(SeleccionInvalida):
                    reservar_turno_de_consulta(
                        self.ana, self.firulais.pk, especialidad,
                        veterinario_id, MANANA_10,
                    )
        self.assertEqual(Turno.objects.count(), 0)


class MigracionDuplicadosTests(SimpleTestCase):
    """El paso de la migracion 0005 que resuelve los turnos duplicados
    antes de crear la restriccion. Con la restriccion puesta ya no se
    pueden crear duplicados en la base de prueba, asi que se prueba con
    turnos simulados (los mismos datos que hay hoy en Aiven)."""

    class _TurnoFalso:
        def __init__(self, pk, veterinario_id, fecha_hora, estado):
            self.id = pk
            self.veterinario_id = veterinario_id
            self.fecha_hora = fecha_hora
            self.estado = estado
            self.guardado = False

        def save(self, update_fields=None):
            self.guardado = True

    def test_cancela_solo_el_duplicado_mas_nuevo(self):
        once_y_media = datetime(2026, 10, 12, 11, 30)
        turnos = [
            self._TurnoFalso(3, 1, datetime(2026, 10, 12, 11, 0), 'PENDIENTE'),
            self._TurnoFalso(1, 1, once_y_media, 'PENDIENTE'),
            self._TurnoFalso(2, 1, once_y_media, 'PENDIENTE'),
            self._TurnoFalso(4, 2, datetime(2026, 10, 13, 16, 0), 'PENDIENTE'),
            self._TurnoFalso(
                5, 20, datetime(2026, 10, 13, 16, 0), 'PENDIENTE',
            ),
        ]

        class _Manager:
            def exclude(self, **filtros):
                return self

            def order_by(self, campo):
                return sorted(turnos, key=lambda t: t.id)

        class _Modelo:
            objects = _Manager()

        class _Apps:
            def get_model(self, app, modelo):
                return _Modelo

        migracion = import_module(
            'atencion.migrations.0005_turnos_consolidados'
        )
        migracion.cancelar_turnos_duplicados(_Apps(), None)

        estados = {t.id: t.estado for t in turnos}
        self.assertEqual(estados, {
            1: 'PENDIENTE', 2: 'CANCELADO', 3: 'PENDIENTE',
            4: 'PENDIENTE', 5: 'PENDIENTE',
        })
        self.assertEqual([t.id for t in turnos if t.guardado], [2])
