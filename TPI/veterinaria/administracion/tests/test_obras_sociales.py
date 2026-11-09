from datetime import time
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from administracion.models import ObraSocial
from administracion.services.obras_sociales import (
    OBRAS_SOCIALES_INICIALES,
    ObraSocialError,
    actualizar_obras_sociales_de_veterinario,
    asignar_obra_social_a_dueno,
    asignar_obras_sociales_de_prueba,
    listar_obras_sociales_activas,
    obras_sociales_de_veterinario,
)
from atencion.tests.test_turnos import crear_veterinario
from clinica.tests.test_mascotas import crear_dueno


def crear_obras_sociales():
    """Las 4 iniciales y una inactiva."""
    call_command('cargar_obras_sociales', stdout=StringIO())
    inactiva = ObraSocial.objects.create(
        nombre='Vieja Cobertura', porcentaje_cobertura=40,
        tope_mensual=5000, cubre_consultas=True, activa=False,
    )
    return {o.nombre: o for o in ObraSocial.objects.all()}, inactiva


class CargarObrasSocialesTests(TestCase):

    def _cargar(self, *args):
        salida = StringIO()
        call_command('cargar_obras_sociales', *args, stdout=salida)
        return salida.getvalue()

    def test_crea_las_cuatro_obras_sociales(self):
        salida = self._cargar()

        self.assertEqual(ObraSocial.objects.count(), 4)
        self.assertIn('4 creadas', salida)
        huellitas = ObraSocial.objects.get(nombre='Huellitas Total')
        self.assertEqual(huellitas.porcentaje_cobertura, 100)
        self.assertEqual(huellitas.tope_mensual, 80000)
        self.assertTrue(huellitas.activa)
        petcare = ObraSocial.objects.get(nombre='PetCare Básico')
        self.assertEqual(petcare.servicios_cubiertos(), ['Vacunación'])

    def test_correrlo_dos_veces_no_duplica(self):
        self._cargar()
        salida = self._cargar()

        self.assertEqual(ObraSocial.objects.count(), 4)
        self.assertIn('0 creadas, 4 ya existían', salida)

    def test_actualiza_las_que_ya_existen_sin_duplicar(self):
        ObraSocial.objects.create(
            nombre='Huellitas Total', porcentaje_cobertura=80,
            tope_mensual=80000, cubre_consultas=True, activa=False,
        )

        salida = self._cargar()
        self._cargar()

        self.assertIn('3 creadas, 1 ya existían', salida)
        self.assertEqual(ObraSocial.objects.count(), 4)
        huellitas = ObraSocial.objects.get(nombre='Huellitas Total')
        self.assertEqual(huellitas.porcentaje_cobertura, 100)
        self.assertTrue(huellitas.cubre_guardia)
        # No reactiva una obra social dada de baja.
        self.assertFalse(huellitas.activa)

    def test_los_datos_coinciden_con_la_lista_inicial(self):
        self._cargar()
        for datos in OBRAS_SOCIALES_INICIALES:
            with self.subTest(nombre=datos['nombre']):
                obra = ObraSocial.objects.get(nombre=datos['nombre'])
                for campo, valor in datos.items():
                    self.assertEqual(getattr(obra, campo), valor)


class AsignarVeterinariosTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.veterinarios = [
            crear_veterinario(
                f'Vet {i}', f'MP-{6000 + i}', 'CLINICA_GENERAL',
                time(8, 0), time(18, 0),
            )
            for i in range(7)
        ]
        cls.inactivo = crear_veterinario(
            'Vet inactivo', 'MP-6999', 'CLINICA_GENERAL',
            time(8, 0), time(18, 0), estado='INACTIVO',
        )

    def _asignaciones(self):
        return {
            v.matricula: sorted(o.nombre for o in v.obras_sociales.all())
            for v in self.veterinarios
        }

    def test_cada_veterinario_activo_recibe_entre_una_y_tres(self):
        call_command(
            'cargar_obras_sociales', '--asignar-veterinarios',
            stdout=StringIO(),
        )

        for matricula, obras in self._asignaciones().items():
            with self.subTest(matricula=matricula):
                self.assertTrue(1 <= len(obras) <= 3)
        self.assertFalse(self.inactivo.obras_sociales.exists())
        cantidades = {len(o) for o in self._asignaciones().values()}
        self.assertEqual(cantidades, {1, 2, 3})

    def test_es_deterministico(self):
        call_command('cargar_obras_sociales', stdout=StringIO())
        asignar_obras_sociales_de_prueba()
        primera = self._asignaciones()
        for veterinario in self.veterinarios:
            veterinario.obras_sociales.clear()

        asignar_obras_sociales_de_prueba()

        self.assertEqual(self._asignaciones(), primera)

    def test_no_pisa_lo_que_eligio_el_veterinario(self):
        call_command('cargar_obras_sociales', stdout=StringIO())
        elegida = ObraSocial.objects.get(nombre='PetCare Básico')
        self.veterinarios[0].obras_sociales.set([elegida])

        cambiados = asignar_obras_sociales_de_prueba()

        self.assertEqual(cambiados, len(self.veterinarios) - 1)
        self.assertEqual(
            list(self.veterinarios[0].obras_sociales.all()), [elegida],
        )

    def test_sin_obras_sociales_no_asigna_nada(self):
        self.assertEqual(asignar_obras_sociales_de_prueba(), 0)


class ObraSocialDeDuenoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.obras, cls.inactiva = crear_obras_sociales()
        cls.vetsalud = cls.obras['VetSalud Plus']
        cls.dueno = crear_dueno()

    def test_lista_solo_las_activas_por_nombre(self):
        nombres = [o.nombre for o in listar_obras_sociales_activas()]

        self.assertEqual(nombres, sorted(
            d['nombre'] for d in OBRAS_SOCIALES_INICIALES
        ))

    def test_elige_una_activa_con_numero_de_afiliado(self):
        asignar_obra_social_a_dueno(self.dueno, self.vetsalud.pk, ' 123-45 ')

        self.dueno.refresh_from_db()
        self.assertEqual(self.dueno.obra_social, self.vetsalud)
        self.assertEqual(self.dueno.numero_afiliado, '123-45')

    def test_sin_numero_de_afiliado_da_error(self):
        with self.assertRaises(ObraSocialError) as error:
            asignar_obra_social_a_dueno(self.dueno, self.vetsalud.pk, '  ')

        self.assertEqual(error.exception.campo, 'numero_afiliado')
        self.dueno.refresh_from_db()
        self.assertIsNone(self.dueno.obra_social)

    def test_sin_obra_social_limpia_el_numero(self):
        asignar_obra_social_a_dueno(self.dueno, self.vetsalud.pk, '999')

        asignar_obra_social_a_dueno(self.dueno, None, '999')

        self.dueno.refresh_from_db()
        self.assertIsNone(self.dueno.obra_social)
        self.assertEqual(self.dueno.numero_afiliado, '')

    def test_inactiva_o_inexistente_da_error(self):
        for obra_social_id in (self.inactiva.pk, 9999, 'abc'):
            with self.subTest(obra_social_id=obra_social_id):
                with self.assertRaises(ObraSocialError) as error:
                    asignar_obra_social_a_dueno(
                        self.dueno, obra_social_id, '123',
                    )
                self.assertEqual(error.exception.campo, 'obra_social')


class ObrasSocialesDeVeterinarioTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.obras, cls.inactiva = crear_obras_sociales()
        cls.veterinario = crear_veterinario(
            'Dra. Laura Fernández', 'MP-5001', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )

    def _ids(self, *nombres):
        return [str(self.obras[nombre].pk) for nombre in nombres]

    def _nombres(self):
        return [
            o.nombre for o in obras_sociales_de_veterinario(self.veterinario)
        ]

    def test_marca_varias(self):
        actualizar_obras_sociales_de_veterinario(
            self.veterinario, self._ids('VetSalud Plus', 'Huellitas Total'),
        )

        self.assertEqual(self._nombres(), ['Huellitas Total', 'VetSalud Plus'])

    def test_guardar_reemplaza_las_anteriores(self):
        actualizar_obras_sociales_de_veterinario(
            self.veterinario, self._ids('VetSalud Plus', 'Huellitas Total'),
        )

        actualizar_obras_sociales_de_veterinario(
            self.veterinario, self._ids('PetCare Básico'),
        )

        self.assertEqual(self._nombres(), ['PetCare Básico'])

    def test_sin_ninguna_las_quita_todas(self):
        actualizar_obras_sociales_de_veterinario(
            self.veterinario, self._ids('VetSalud Plus'),
        )

        actualizar_obras_sociales_de_veterinario(self.veterinario, [])

        self.assertEqual(self._nombres(), [])

    def test_inactiva_o_invalida_da_error_y_no_cambia_nada(self):
        actualizar_obras_sociales_de_veterinario(
            self.veterinario, self._ids('VetSalud Plus'),
        )
        for extra in (str(self.inactiva.pk), '9999', 'abc'):
            with self.subTest(extra=extra):
                with self.assertRaises(ObraSocialError):
                    actualizar_obras_sociales_de_veterinario(
                        self.veterinario,
                        self._ids('Huellitas Total') + [extra],
                    )
                self.assertEqual(self._nombres(), ['VetSalud Plus'])
