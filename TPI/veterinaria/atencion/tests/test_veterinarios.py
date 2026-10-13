from datetime import time
from importlib import import_module
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from atencion.models import HorarioAtencion, Veterinario
from atencion.services.veterinarios import cargar_veterinarios_iniciales


class CargarVeterinariosTests(TestCase):

    def test_crea_21_veterinarios_activos_3_por_especialidad(self):
        resumen = cargar_veterinarios_iniciales()

        self.assertEqual(Veterinario.objects.count(), 21)
        self.assertEqual(
            Veterinario.objects.filter(estado='ACTIVO').count(), 21,
        )
        for especialidad in Veterinario.Especialidad:
            with self.subTest(especialidad=especialidad):
                self.assertEqual(
                    Veterinario.objects.filter(
                        especialidad=especialidad,
                    ).count(),
                    3,
                )
                self.assertEqual(
                    resumen[especialidad.label],
                    {'creados': 3, 'existentes': 0},
                )

    def test_matriculas_y_nombres_no_se_repiten(self):
        cargar_veterinarios_iniciales()

        matriculas = set(
            Veterinario.objects.values_list('matricula', flat=True)
        )
        nombres = set(Veterinario.objects.values_list('nombre', flat=True))

        self.assertEqual(len(matriculas), 21)
        self.assertEqual(len(nombres), 21)
        self.assertTrue(all(m.startswith('MP-5') for m in matriculas))
        self.assertFalse(matriculas & {'MP-1234', 'MP-5678', 'MP-9012'})

    def test_cada_uno_tiene_horario_de_lunes_a_sabado(self):
        cargar_veterinarios_iniciales()

        for veterinario in Veterinario.objects.all():
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
            with self.subTest(especialidad=especialidad):
                inicios = set(
                    HorarioAtencion.objects.filter(
                        veterinario__especialidad=especialidad,
                    ).values_list('hora_inicio', flat=True)
                )
                self.assertEqual(inicios, {time(8), time(13)})

    def test_correrlo_dos_veces_no_duplica(self):
        cargar_veterinarios_iniciales()

        resumen = cargar_veterinarios_iniciales()

        self.assertEqual(Veterinario.objects.count(), 21)
        self.assertEqual(HorarioAtencion.objects.count(), 21 * 6)
        self.assertTrue(all(
            cantidades == {'creados': 0, 'existentes': 3}
            for cantidades in resumen.values()
        ))

    def test_no_pisa_un_veterinario_que_ya_tiene_esa_matricula(self):
        Veterinario.objects.create(
            nombre='Dr. Ya Existente', matricula='MP-5001',
            especialidad='CARDIOLOGIA',
        )

        cargar_veterinarios_iniciales()

        existente = Veterinario.objects.get(matricula='MP-5001')
        self.assertEqual(existente.nombre, 'Dr. Ya Existente')
        self.assertEqual(existente.horarios_atencion.count(), 0)
        self.assertEqual(Veterinario.objects.count(), 21)

    def test_los_de_vacunacion_se_crean_solo_si_no_hay_ninguno(self):
        Veterinario.objects.create(
            nombre='Dra. Vacunadora Existente', matricula='MP-7000',
            especialidad=Veterinario.Especialidad.VACUNACION,
        )

        resumen = cargar_veterinarios_iniciales()

        de_vacunacion = Veterinario.objects.filter(especialidad='VACUNACION')
        self.assertEqual(
            list(de_vacunacion.values_list('matricula', flat=True)),
            ['MP-7000'],
        )
        self.assertEqual(
            resumen['Vacunación'], {'creados': 0, 'existentes': 1},
        )
        self.assertEqual(Veterinario.objects.count(), 19)

    def test_comando_muestra_el_resumen(self):
        salida = StringIO()

        call_command('cargar_veterinarios', stdout=salida)

        self.assertIn(
            'Cardiología: 3 creados, 0 ya existían', salida.getvalue(),
        )
        self.assertIn('Total: 21 creados, 0 ya existían.', salida.getvalue())


class MigracionEspecialidadTests(TestCase):
    """La conversion de datos de la migracion 0003 (especialidad de
    texto libre a choices), con los valores que hay hoy en Aiven."""

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
