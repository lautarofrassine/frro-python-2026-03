from collections import Counter
from datetime import datetime, time
from importlib import import_module
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from atencion.models import HorarioAtencion, Veterinario
from atencion.services.turnos import turnos_disponibles
from atencion.services.veterinarios import cargar_veterinarios_iniciales

ZONA = ZoneInfo('America/Argentina/Buenos_Aires')
GUARDIA = Veterinario.Especialidad.GUARDIA
# 18 de consulta + 3 de vacunacion + 6 de guardia.
TOTAL = 27
HORARIOS = 21 * 6 + 6 * 7


class CargarVeterinariosTests(TestCase):

    def test_crea_3_por_especialidad_y_6_de_guardia_todos_activos(self):
        resumen = cargar_veterinarios_iniciales()

        self.assertEqual(Veterinario.objects.count(), TOTAL)
        self.assertEqual(
            Veterinario.objects.filter(estado='ACTIVO').count(), TOTAL,
        )
        for especialidad in Veterinario.Especialidad:
            esperados = 6 if especialidad == GUARDIA else 3
            with self.subTest(especialidad=especialidad):
                self.assertEqual(
                    Veterinario.objects.filter(
                        especialidad=especialidad,
                    ).count(),
                    esperados,
                )
                self.assertEqual(
                    resumen[especialidad.label],
                    {'creados': esperados, 'existentes': 0},
                )

    def test_matriculas_y_nombres_no_se_repiten(self):
        cargar_veterinarios_iniciales()

        matriculas = set(
            Veterinario.objects.values_list('matricula', flat=True)
        )
        nombres = set(Veterinario.objects.values_list('nombre', flat=True))

        self.assertEqual(len(matriculas), TOTAL)
        self.assertEqual(len(nombres), TOTAL)
        self.assertTrue(all(m.startswith('MP-5') for m in matriculas))
        self.assertFalse(matriculas & {'MP-1234', 'MP-5678', 'MP-9012'})

    def test_los_de_consulta_atienden_de_lunes_a_sabado(self):
        cargar_veterinarios_iniciales()

        for veterinario in Veterinario.objects.exclude(especialidad=GUARDIA):
            with self.subTest(veterinario=veterinario.matricula):
                horarios = list(veterinario.horarios_atencion.all())
                self.assertEqual(
                    sorted(h.dia_semana for h in horarios), [0, 1, 2, 3, 4, 5],
                )
                franjas = {(h.hora_inicio, h.hora_fin) for h in horarios}
                self.assertEqual(len(franjas), 1)
                self.assertIn(
                    franjas.pop(),
                    {(time(8), time(13)), (time(13), time(19))},
                )

    def test_cada_especialidad_tiene_cobertura_de_manana_y_de_tarde(self):
        cargar_veterinarios_iniciales()

        for especialidad in Veterinario.Especialidad:
            if especialidad == GUARDIA:
                continue
            with self.subTest(especialidad=especialidad):
                inicios = set(
                    HorarioAtencion.objects.filter(
                        veterinario__especialidad=especialidad,
                    ).values_list('hora_inicio', flat=True)
                )
                self.assertEqual(inicios, {time(8), time(13)})

    def test_la_guardia_tiene_2_veterinarios_por_franja_los_7_dias(self):
        cargar_veterinarios_iniciales()

        horarios = HorarioAtencion.objects.filter(
            veterinario__especialidad=GUARDIA,
        )
        por_dia_y_franja = Counter(
            (h.dia_semana, h.hora_inicio, h.hora_fin) for h in horarios
        )

        self.assertEqual(len(por_dia_y_franja), 7 * 3)
        self.assertEqual(set(por_dia_y_franja.values()), {2})
        for dia in range(7):
            with self.subTest(dia=dia):
                franjas = sorted(
                    (inicio, fin)
                    for d, inicio, fin in por_dia_y_franja if d == dia
                )
                self.assertEqual(franjas, [
                    (time(0), time(8)),
                    (time(8), time(16)),
                    (time(16), time(23, 59)),
                ])

    def test_la_guardia_cubre_las_24_horas_de_un_domingo(self):
        cargar_veterinarios_iniciales()
        ahora = datetime(2026, 10, 14, 12, 0, tzinfo=ZONA)

        with patch('django.utils.timezone.now', return_value=ahora):
            libres = turnos_disponibles(
                especialidad=GUARDIA,
                desde=datetime(2026, 10, 17, 23, 59, tzinfo=ZONA),
                hasta=datetime(2026, 10, 18, 23, 59, tzinfo=ZONA),
            )

        por_hora = Counter(h['fecha_hora'] for h in libres)
        # 48 turnos de 30 minutos, de 00:00 a 23:30, con 2 veterinarios.
        self.assertEqual(len(por_hora), 48)
        self.assertEqual(set(por_hora.values()), {2})
        self.assertEqual(
            por_hora[datetime(2026, 10, 18, 3, 0, tzinfo=ZONA)], 2,
        )
        self.assertEqual(
            max(por_hora), datetime(2026, 10, 18, 23, 30, tzinfo=ZONA),
        )

    def test_correrlo_dos_veces_no_duplica(self):
        cargar_veterinarios_iniciales()

        resumen = cargar_veterinarios_iniciales()

        self.assertEqual(Veterinario.objects.count(), TOTAL)
        self.assertEqual(HorarioAtencion.objects.count(), HORARIOS)
        self.assertEqual(
            sum(c['creados'] for c in resumen.values()), 0,
        )
        self.assertEqual(
            sum(c['existentes'] for c in resumen.values()), TOTAL,
        )
        self.assertEqual(
            resumen['Guardia'], {'creados': 0, 'existentes': 6},
        )

    def test_no_pisa_un_veterinario_que_ya_tiene_esa_matricula(self):
        Veterinario.objects.create(
            nombre='Dr. Ya Existente', matricula='MP-5001',
            especialidad='CARDIOLOGIA',
        )

        cargar_veterinarios_iniciales()

        existente = Veterinario.objects.get(matricula='MP-5001')
        self.assertEqual(existente.nombre, 'Dr. Ya Existente')
        self.assertEqual(existente.horarios_atencion.count(), 0)
        self.assertEqual(Veterinario.objects.count(), TOTAL)

    def test_vacunacion_y_guardia_se_crean_solo_si_no_hay_ninguno(self):
        Veterinario.objects.create(
            nombre='Dra. Vacunadora Existente', matricula='MP-7000',
            especialidad=Veterinario.Especialidad.VACUNACION,
        )
        Veterinario.objects.create(
            nombre='Dr. Guardia Existente', matricula='MP-8000',
            especialidad=GUARDIA,
        )

        resumen = cargar_veterinarios_iniciales()

        for especialidad, matricula in (
            ('VACUNACION', 'MP-7000'), ('GUARDIA', 'MP-8000'),
        ):
            with self.subTest(especialidad=especialidad):
                self.assertEqual(
                    list(
                        Veterinario.objects.filter(
                            especialidad=especialidad,
                        ).values_list('matricula', flat=True)
                    ),
                    [matricula],
                )
        self.assertEqual(
            resumen['Vacunación'], {'creados': 0, 'existentes': 1},
        )
        self.assertEqual(resumen['Guardia'], {'creados': 0, 'existentes': 1})
        self.assertEqual(Veterinario.objects.count(), 18 + 2)

    def test_comando_muestra_el_resumen(self):
        salida = StringIO()

        call_command('cargar_veterinarios', stdout=salida)

        self.assertIn(
            'Cardiología: 3 creados, 0 ya existían', salida.getvalue(),
        )
        self.assertIn('Guardia: 6 creados, 0 ya existían', salida.getvalue())
        self.assertIn('Total: 27 creados, 0 ya existían.', salida.getvalue())


class MigracionEspecialidadTests(TestCase):
    """La conversion de datos de la migracion 0003 (especialidad de
    texto libre a choices), con los valores que habia en Aiven."""

    def test_convierte_los_que_encajan_y_deja_el_resto(self):
        general = Veterinario.objects.create(
            nombre='A', matricula='MP-1234', especialidad='Clínica General',
        )
        dermato = Veterinario.objects.create(
            nombre='B', matricula='MP-9012', especialidad='Dermatología',
        )
        cirugia = Veterinario.objects.create(
            nombre='C', matricula='MP-5678', especialidad='Cirugía',
        )
        migracion = import_module(
            'atencion.migrations.0003_veterinario_especialidad_choices'
        )

        migracion.texto_libre_a_choices(apps, None)

        for veterinario in (general, dermato, cirugia):
            veterinario.refresh_from_db()
        self.assertEqual(general.especialidad, 'CLINICA_GENERAL')
        self.assertEqual(dermato.especialidad, 'DERMATOLOGIA')
        self.assertEqual(cirugia.especialidad, 'Cirugía')
