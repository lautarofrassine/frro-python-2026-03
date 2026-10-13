from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from clinica.models import Dueno, Mascota
from clinica.services.mascotas import (
    MascotaError,
    MascotaNoEncontrada,
    actualizar_mascota,
    calcular_edad,
    dar_de_baja_mascota,
    edad_en_anios,
    listar_mascotas,
    obtener_mascota_de_dueno,
    registrar_mascota,
)


def crear_dueno(email='ana@mail.com', dni='28111222', nombre='Ana'):
    # Sin contraseña (unusable): estos tests no necesitan pagar el hash.
    usuario = get_user_model().objects.create_user(
        username=email, first_name=nombre,
    )
    return Dueno.objects.create(
        usuario=usuario, nombre=nombre, apellido='Gómez', dni=dni,
        email=email, telefono='341 555-0000',
    )


def datos_mascota(**overrides):
    datos = {
        'nombre': 'Firulais',
        'especie': 'PERRO',
        'raza': 'Mestizo',
        'fecha_nacimiento': date(2020, 5, 10),
        'peso_kg': Decimal('12.50'),
    }
    datos.update(overrides)
    return datos


class RegistrarMascotaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')

    def test_crea_la_mascota_vinculada_al_dueno(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        self.assertIsNotNone(mascota.pk)
        self.assertEqual(mascota.dueno, self.ana)
        self.assertTrue(mascota.activo)
        self.assertIsNotNone(mascota.fecha_alta)
        self.assertEqual(mascota.especie, Mascota.Especie.PERRO)

    def test_especie_en_minuscula_se_normaliza(self):
        mascota = registrar_mascota(self.ana, **datos_mascota(especie='gato'))

        self.assertEqual(mascota.especie, Mascota.Especie.GATO)

    def test_nombre_repetido_con_otras_mayusculas_da_error(self):
        registrar_mascota(self.ana, **datos_mascota(nombre='Firulais'))

        with self.assertRaises(MascotaError) as ctx:
            registrar_mascota(self.ana, **datos_mascota(nombre=' FIRULAIS '))

        self.assertEqual(ctx.exception.campo, 'nombre')
        self.assertEqual(Mascota.objects.filter(dueno=self.ana).count(), 1)

    def test_mismo_nombre_en_otro_dueno_esta_permitido(self):
        registrar_mascota(self.ana, **datos_mascota())

        mascota = registrar_mascota(self.beto, **datos_mascota())

        self.assertEqual(mascota.dueno, self.beto)

    def test_nombre_de_mascota_dada_de_baja_se_puede_reutilizar(self):
        vieja = registrar_mascota(self.ana, **datos_mascota())
        dar_de_baja_mascota(self.ana, vieja.pk)

        nueva = registrar_mascota(self.ana, **datos_mascota())

        self.assertNotEqual(nueva.pk, vieja.pk)
        self.assertTrue(nueva.activo)

    def test_fecha_de_nacimiento_futura_da_error(self):
        manana = timezone.localdate() + timedelta(days=1)

        with self.assertRaises(MascotaError) as ctx:
            registrar_mascota(
                self.ana, **datos_mascota(fecha_nacimiento=manana)
            )

        self.assertEqual(ctx.exception.campo, 'fecha_nacimiento')

    def test_peso_fuera_de_rango_da_error(self):
        for peso in ('0', '-3', '120', '150.5'):
            with self.subTest(peso=peso):
                with self.assertRaises(MascotaError) as ctx:
                    registrar_mascota(
                        self.ana, **datos_mascota(peso_kg=Decimal(peso))
                    )
                self.assertEqual(ctx.exception.campo, 'peso_kg')
        self.assertEqual(Mascota.objects.count(), 0)

    def test_peso_en_el_borde_valido(self):
        mascota = registrar_mascota(
            self.ana, **datos_mascota(peso_kg=Decimal('119.99'))
        )

        self.assertEqual(mascota.peso_kg, Decimal('119.99'))

    def test_especie_distinta_de_perro_o_gato_da_error(self):
        with self.assertRaises(MascotaError) as ctx:
            registrar_mascota(self.ana, **datos_mascota(especie='CONEJO'))

        self.assertEqual(ctx.exception.campo, 'especie')
        self.assertEqual(Mascota.objects.count(), 0)

    def test_personal_sin_dueno_no_puede_registrar(self):
        with self.assertRaises(MascotaError):
            registrar_mascota(None, **datos_mascota())


class ListarYObtenerMascotasTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')

    def test_listar_no_muestra_bajas_ni_mascotas_de_otros(self):
        registrar_mascota(self.ana, **datos_mascota(nombre='Toby'))
        registrar_mascota(self.ana, **datos_mascota(nombre='luna'))
        baja = registrar_mascota(self.ana, **datos_mascota(nombre='Rocky'))
        dar_de_baja_mascota(self.ana, baja.pk)
        registrar_mascota(self.beto, **datos_mascota(nombre='Michi'))

        nombres = [m.nombre for m in listar_mascotas(self.ana)]

        self.assertEqual(nombres, ['luna', 'Toby'])

    def test_listar_para_personal_sin_dueno_devuelve_vacio(self):
        self.assertEqual(listar_mascotas(None), [])

    def test_obtener_mascota_de_otro_dueno_no_la_encuentra(self):
        mascota = registrar_mascota(self.beto, **datos_mascota())

        with self.assertRaises(MascotaNoEncontrada):
            obtener_mascota_de_dueno(self.ana, mascota.pk)

    def test_obtener_mascota_dada_de_baja_no_la_encuentra(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())
        dar_de_baja_mascota(self.ana, mascota.pk)

        with self.assertRaises(MascotaNoEncontrada):
            obtener_mascota_de_dueno(self.ana, mascota.pk)


class ActualizarYBajaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')

    def test_actualizar_con_el_mismo_nombre_no_choca_consigo_misma(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        actualizada = actualizar_mascota(
            self.ana, mascota.pk, nombre='firulais', peso_kg=Decimal('14'),
        )

        self.assertEqual(actualizada.nombre, 'firulais')
        mascota.refresh_from_db()
        self.assertEqual(mascota.peso_kg, Decimal('14.00'))

    def test_actualizar_a_un_nombre_de_otra_mascota_activa_da_error(self):
        registrar_mascota(self.ana, **datos_mascota(nombre='Toby'))
        luna = registrar_mascota(self.ana, **datos_mascota(nombre='Luna'))

        with self.assertRaises(MascotaError):
            actualizar_mascota(self.ana, luna.pk, nombre='TOBY')

    def test_actualizar_aplica_las_mismas_validaciones(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        with self.assertRaises(MascotaError):
            actualizar_mascota(self.ana, mascota.pk, peso_kg=Decimal('0'))

    def test_actualizar_mascota_de_otro_dueno_no_la_encuentra(self):
        mascota = registrar_mascota(self.beto, **datos_mascota())

        with self.assertRaises(MascotaNoEncontrada):
            actualizar_mascota(self.ana, mascota.pk, nombre='Hackeado')

    def test_dar_de_baja_es_logica(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        dar_de_baja_mascota(self.ana, mascota.pk)

        mascota.refresh_from_db()
        self.assertFalse(mascota.activo)

    def test_dar_de_baja_mascota_de_otro_dueno_no_la_encuentra(self):
        mascota = registrar_mascota(self.beto, **datos_mascota())

        with self.assertRaises(MascotaNoEncontrada):
            dar_de_baja_mascota(self.ana, mascota.pk)
        mascota.refresh_from_db()
        self.assertTrue(mascota.activo)


@patch('clinica.services.mascotas._hoy', return_value=date(2026, 10, 9))
class CalcularEdadTests(SimpleTestCase):

    def _edad(self, nacimiento):
        return calcular_edad(Mascota(fecha_nacimiento=nacimiento))

    def test_anios_exactos(self, _hoy):
        self.assertEqual(self._edad(date(2023, 10, 9)), '3 años')
        self.assertEqual(self._edad(date(2025, 10, 9)), '1 año')

    def test_solo_meses(self, _hoy):
        self.assertEqual(self._edad(date(2026, 2, 1)), '8 meses')
        self.assertEqual(self._edad(date(2026, 9, 9)), '1 mes')

    def test_anios_y_meses(self, _hoy):
        self.assertEqual(self._edad(date(2025, 8, 9)), '1 año y 2 meses')
        self.assertEqual(self._edad(date(2021, 9, 1)), '5 años y 1 mes')

    def test_no_cuenta_el_mes_si_todavia_no_llego_el_dia(self, _hoy):
        self.assertEqual(self._edad(date(2025, 8, 10)), '1 año y 1 mes')

    def test_recien_nacido(self, _hoy):
        self.assertEqual(self._edad(date(2026, 10, 1)), 'Menos de 1 mes')


class EdadEnAniosTests(SimpleTestCase):
    HOY = date(2026, 10, 14)

    def _edad(self, nacimiento):
        return edad_en_anios(
            Mascota(nombre='Firulais', fecha_nacimiento=nacimiento), self.HOY,
        )

    def test_recien_nacido(self):
        self.assertEqual(self._edad(date(2026, 10, 14)), 0)
        self.assertEqual(self._edad(date(2026, 10, 1)), 0)

    def test_seis_meses(self):
        self.assertEqual(self._edad(date(2026, 4, 14)), 0.5)

    def test_dos_anios_y_tres_meses(self):
        self.assertEqual(self._edad(date(2024, 7, 14)), 2.25)

    def test_redondea_a_dos_decimales(self):
        # 6 años y 5 meses = 77 meses = 6.4166...
        self.assertEqual(self._edad(date(2020, 5, 10)), 6.42)

    def test_usa_la_fecha_de_hoy_si_no_se_indica(self):
        with patch('clinica.services.mascotas._hoy', return_value=self.HOY):
            edad = edad_en_anios(Mascota(fecha_nacimiento=date(2025, 10, 14)))

        self.assertEqual(edad, 1)

    def test_sin_fecha_de_nacimiento_da_un_error_claro(self):
        with self.assertRaises(MascotaError) as ctx:
            self._edad(None)

        self.assertIn('fecha de nacimiento', str(ctx.exception))
        self.assertEqual(ctx.exception.campo, 'fecha_nacimiento')
