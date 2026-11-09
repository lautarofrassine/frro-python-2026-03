"""Precios por veterinario. "Hoy" es el miercoles 14/10/2026 a las 12:00
(TurnosBase congela timezone.now)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from administracion.models import Pago
from atencion.models import PrecioVeterinario
from atencion.services.precios import (
    PrecioError,
    eliminar_cambio_de_precio,
    fecha_minima_de_cambio,
    historial_de_precios,
    precio_vigente,
    programar_cambio_de_precio,
)
from atencion.tests.test_turnos import AHORA, MANANA_10, ZONA, TurnosBase

HOY = AHORA.date()
MINIMA = HOY + timedelta(days=14)  # 28/10/2026
URL_PRECIOS = reverse('veterinario:precios')


def precio(veterinario, monto, vigente_desde):
    return PrecioVeterinario.objects.create(
        veterinario=veterinario, monto=Decimal(monto),
        vigente_desde=vigente_desde,
    )


class PrecioVigenteTests(TurnosBase):

    def test_sin_precio_usa_el_de_la_especialidad(self):
        self.assertEqual(precio_vigente(self.clinico), Decimal('15000'))
        self.assertEqual(
            precio_vigente(self.cardiologo, date(2030, 1, 1)),
            Decimal('28000'),
        )

    def test_toma_el_cambio_mas_reciente_hasta_la_fecha(self):
        precio(self.clinico, '18000', date(2026, 1, 1))
        precio(self.clinico, '20000', date(2026, 6, 1))
        precio(self.clinico, '25000', date(2026, 11, 1))
        casos = (
            (date(2025, 12, 31), Decimal('15000')),  # antes del primero
            (date(2026, 1, 1), Decimal('18000')),
            (date(2026, 5, 31), Decimal('18000')),
            (date(2026, 6, 1), Decimal('20000')),
            (HOY, Decimal('20000')),
            (date(2026, 10, 31), Decimal('20000')),
            (date(2026, 11, 1), Decimal('25000')),
            (date(2027, 3, 1), Decimal('25000')),
        )
        for fecha, esperado in casos:
            with self.subTest(fecha=fecha):
                self.assertEqual(precio_vigente(self.clinico, fecha), esperado)

    def test_acepta_datetime_y_usa_el_dia_local(self):
        precio(self.clinico, '20000', date(2026, 11, 1))
        # 31/10 a las 23:30 en Argentina es 1/11 en UTC: sigue siendo 31/10.
        noche = datetime(2026, 10, 31, 23, 30, tzinfo=ZONA)

        self.assertEqual(precio_vigente(self.clinico, noche), Decimal('15000'))
        self.assertEqual(
            precio_vigente(self.clinico, noche + timedelta(hours=1)),
            Decimal('20000'),
        )

    def test_no_mezcla_veterinarios(self):
        precio(self.cardiologo, '40000', date(2026, 1, 1))

        self.assertEqual(precio_vigente(self.clinico), Decimal('15000'))
        self.assertEqual(precio_vigente(self.cardiologo), Decimal('40000'))


class ProgramarCambioTests(TurnosBase):

    def test_la_fecha_minima_es_hoy_mas_14_dias(self):
        self.assertEqual(fecha_minima_de_cambio(), date(2026, 10, 28))

    def test_programa_desde_la_fecha_minima(self):
        nuevo = programar_cambio_de_precio(self.clinico, '19500.50', MINIMA)

        self.assertEqual(nuevo.monto, Decimal('19500.50'))
        self.assertEqual(nuevo.vigente_desde, MINIMA)
        # Hoy sigue rigiendo el anterior.
        self.assertEqual(precio_vigente(self.clinico), Decimal('15000'))
        self.assertEqual(
            precio_vigente(self.clinico, MINIMA), Decimal('19500.50'),
        )

    def test_con_menos_de_14_dias_da_error(self):
        for fecha in (HOY, HOY - timedelta(days=1), MINIMA - timedelta(1)):
            with self.subTest(fecha=fecha):
                with self.assertRaises(PrecioError) as error:
                    programar_cambio_de_precio(self.clinico, 20000, fecha)
                self.assertEqual(error.exception.campo, 'vigente_desde')
                self.assertIn('28/10/2026', str(error.exception))
        self.assertFalse(PrecioVeterinario.objects.exists())

    def test_fecha_repetida_da_error(self):
        programar_cambio_de_precio(self.clinico, 20000, MINIMA)

        with self.assertRaises(PrecioError) as error:
            programar_cambio_de_precio(self.clinico, 21000, MINIMA)

        self.assertEqual(error.exception.campo, 'vigente_desde')
        self.assertEqual(self.clinico.precios.count(), 1)
        # Otro veterinario si puede usar esa fecha.
        programar_cambio_de_precio(self.cardiologo, 30000, MINIMA)

    def test_monto_cero_negativo_o_invalido_da_error(self):
        for monto in (0, '-100', 'abc', None):
            with self.subTest(monto=monto):
                with self.assertRaises(PrecioError) as error:
                    programar_cambio_de_precio(self.clinico, monto, MINIMA)
                self.assertEqual(error.exception.campo, 'monto')
        self.assertFalse(PrecioVeterinario.objects.exists())


class EliminarCambioTests(TurnosBase):

    def test_elimina_uno_que_todavia_no_rige(self):
        futuro = precio(self.clinico, '20000', HOY + timedelta(days=1))

        eliminar_cambio_de_precio(self.clinico, futuro.pk)

        self.assertFalse(PrecioVeterinario.objects.exists())

    def test_uno_vigente_o_pasado_no_se_elimina(self):
        pasado = precio(self.clinico, '18000', date(2026, 1, 1))
        de_hoy = precio(self.clinico, '20000', HOY)
        for registro in (pasado, de_hoy):
            with self.subTest(vigente_desde=registro.vigente_desde):
                with self.assertRaises(PrecioError):
                    eliminar_cambio_de_precio(self.clinico, registro.pk)
        self.assertEqual(PrecioVeterinario.objects.count(), 2)

    def test_uno_de_otro_veterinario_o_inexistente_da_error(self):
        ajeno = precio(self.cardiologo, '40000', MINIMA)
        for precio_id in (ajeno.pk, 9999, 'abc'):
            with self.subTest(precio_id=precio_id):
                with self.assertRaises(PrecioError):
                    eliminar_cambio_de_precio(self.clinico, precio_id)
        self.assertTrue(PrecioVeterinario.objects.filter(pk=ajeno.pk).exists())


class HistorialTests(TurnosBase):

    def test_separa_vigente_programados_y_anteriores(self):
        viejo = precio(self.clinico, '15000', date(2026, 1, 1))
        anterior = precio(self.clinico, '18000', date(2026, 6, 1))
        vigente = precio(self.clinico, '20000', date(2026, 9, 1))
        lejano = precio(self.clinico, '26000', date(2027, 1, 1))
        proximo = precio(self.clinico, '23000', date(2026, 11, 1))

        historial = historial_de_precios(self.clinico)

        self.assertEqual(historial['vigente'], vigente)
        self.assertEqual(historial['monto_vigente'], Decimal('20000'))
        self.assertEqual(historial['programados'], [proximo, lejano])
        self.assertEqual(historial['anteriores'], [anterior, viejo])

    def test_sin_precios_muestra_el_de_la_especialidad(self):
        historial = historial_de_precios(self.cardiologo)

        self.assertIsNone(historial['vigente'])
        self.assertEqual(historial['monto_vigente'], Decimal('28000'))
        self.assertEqual(historial['programados'], [])
        self.assertEqual(historial['anteriores'], [])


class PrecioDelTurnoTests(TurnosBase):

    def test_reservar_usa_el_precio_vigente_en_la_fecha_del_turno(self):
        precio(self.clinico, '18000', date(2026, 1, 1))
        precio(self.clinico, '22000', date(2026, 10, 16))

        turno_jueves = self.reservar()  # 15/10
        turno_viernes = self.reservar(
            fecha_hora=MANANA_10 + timedelta(days=1),  # 16/10
        )

        self.assertEqual(
            turno_jueves.pagos.get().monto_total, Decimal('18000'),
        )
        self.assertEqual(
            turno_viernes.pagos.get().monto_total, Decimal('22000'),
        )

    def test_un_cambio_posterior_no_modifica_el_pago(self):
        turno = self.reservar(
            fecha_hora=datetime.combine(
                date(2026, 11, 2), time(10, 0), tzinfo=ZONA,
            ),
        )
        self.assertEqual(turno.pagos.get().monto_total, Decimal('15000'))

        programar_cambio_de_precio(self.clinico, 50000, MINIMA)

        self.assertEqual(
            Pago.objects.get(turno=turno).monto_total, Decimal('15000'),
        )
        self.assertEqual(
            precio_vigente(self.clinico, turno.fecha_hora), Decimal('50000'),
        )


class PreciosVistasBase(TurnosBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.usuario_vet = get_user_model().objects.create_user(
            username='laura.fernandez@clinicavet24.com',
        )
        cls.clinico.usuario = cls.usuario_vet
        cls.clinico.save()

    def setUp(self):
        super().setUp()
        parche = patch(
            'clinica.services.mascotas._hoy', return_value=HOY,
        )
        parche.start()
        self.addCleanup(parche.stop)


class MisPreciosViewTests(PreciosVistasBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario_vet)

    def test_dueno_recibe_403(self):
        self.client.force_login(self.ana.usuario)
        futuro = precio(self.clinico, '20000', MINIMA)

        self.assertEqual(self.client.get(URL_PRECIOS).status_code, 403)
        eliminar = reverse('veterinario:precio_eliminar', args=[futuro.pk])
        self.assertEqual(self.client.post(eliminar).status_code, 403)
        self.assertTrue(PrecioVeterinario.objects.exists())

    def test_muestra_vigente_programados_anteriores_y_formulario(self):
        precio(self.clinico, '18000', date(2026, 1, 1))
        precio(self.clinico, '20000', date(2026, 6, 1))
        precio(self.clinico, '24000', date(2026, 12, 1))

        response = self.client.get(URL_PRECIOS)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/vet_precios.html')
        self.assertRegex(contenido, r'id="precio-vigente">\s*\$20\.000')
        self.assertIn('$24.000', contenido)
        self.assertIn('01/12/2026', contenido)
        self.assertIn('$18.000', contenido)
        self.assertIn('min="2026-10-28"', contenido)
        self.assertIn('type="date"', contenido)
        self.assertIn('rigen como mínimo 14 días', contenido)
        self.assertEqual(contenido.count('Eliminar'), 1)

    def test_programar_un_precio(self):
        response = self.client.post(
            URL_PRECIOS, {'monto': '21000', 'vigente_desde': '2026-11-02'},
            follow=True,
        )

        self.assertRedirects(response, URL_PRECIOS)
        self.assertContains(response, 'desde el 02/11/2026')
        self.assertEqual(
            precio_vigente(self.clinico, date(2026, 11, 2)), Decimal('21000'),
        )

    def test_programar_con_menos_de_14_dias_muestra_el_error(self):
        response = self.client.post(
            URL_PRECIOS, {'monto': '21000', 'vigente_desde': '2026-10-20'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'El nuevo precio debe regir desde el 28/10/2026',
        )
        self.assertFalse(PrecioVeterinario.objects.exists())

    def test_eliminar_un_cambio_programado(self):
        futuro = precio(self.clinico, '20000', MINIMA)

        response = self.client.post(
            reverse('veterinario:precio_eliminar', args=[futuro.pk]),
            follow=True,
        )

        self.assertRedirects(response, URL_PRECIOS)
        self.assertContains(response, 'Se eliminó el cambio de precio.')
        self.assertFalse(PrecioVeterinario.objects.exists())

    def test_eliminar_uno_vigente_muestra_el_error(self):
        vigente = precio(self.clinico, '20000', date(2026, 6, 1))

        response = self.client.post(
            reverse('veterinario:precio_eliminar', args=[vigente.pk]),
            follow=True,
        )

        self.assertContains(response, 'todavía no rigen')
        self.assertTrue(PrecioVeterinario.objects.exists())

    def test_la_agenda_muestra_el_precio_vigente(self):
        precio(self.clinico, '19000', date(2026, 1, 1))

        response = self.client.get(reverse('veterinario:agenda'))

        self.assertContains(response, 'Precio por atención')
        self.assertContains(response, '$19.000')


class SacarTurnoConPrecioTests(PreciosVistasBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana.usuario)

    def test_horarios_y_confirmacion_usan_el_precio_del_veterinario(self):
        precio(self.cardiologo, '31000', date(2026, 1, 1))
        precio(self.cardiologo, '35000', date(2026, 10, 16))
        url = reverse('atencion:turno_nuevo')

        response = self.client.get(url, {
            'mascota': self.firulais.pk, 'especialidad': 'CARDIOLOGIA',
        })

        dias = {
            d['fecha']: {h['precio'] for h in d['horarios']}
            for d in response.context['semana']['dias'] if d['horarios']
        }
        self.assertEqual(dias[date(2026, 10, 15)], {Decimal('31000')})
        self.assertEqual(dias[date(2026, 10, 16)], {Decimal('35000')})
        self.assertContains(response, '$35.000')

        confirmar = self.client.get(reverse('atencion:turno_confirmar'), {
            'mascota': self.firulais.pk,
            'especialidad': 'CARDIOLOGIA',
            'veterinario': self.cardiologo.pk,
            'fecha_hora': datetime(
                2026, 10, 16, 15, 0, tzinfo=ZONA,
            ).isoformat(),
        })
        self.assertEqual(confirmar.context['horario']['precio'], 35000)
        self.assertContains(confirmar, '$35.000')


class CargarPreciosInicialesTests(TurnosBase):

    def test_crea_el_de_la_especialidad_y_no_duplica(self):
        propio = precio(self.cardiologo, '40000', date(2026, 3, 1))
        salida = StringIO()

        call_command('cargar_precios_iniciales', stdout=salida)
        call_command('cargar_precios_iniciales', stdout=StringIO())

        self.assertIn('Precios iniciales creados: 1.', salida.getvalue())
        inicial = self.clinico.precios.get()
        self.assertEqual(inicial.monto, Decimal('15000'))
        self.assertEqual(inicial.vigente_desde, date(2026, 1, 1))
        # No toca al que ya tenia precio.
        self.assertEqual(list(self.cardiologo.precios.all()), [propio])
