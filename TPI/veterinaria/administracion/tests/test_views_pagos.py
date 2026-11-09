"""Pantallas de pagos del dueño y cobro en efectivo del veterinario.
Mercado Pago esta mockeado: nunca se llama a la API real."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from administracion.models import Pago
from administracion.services.pagos import registrar_cobro_efectivo
from administracion.tests.test_pagos import (
    SDK,
    TOKEN_PRUEBA,
    PagosBase,
    respuesta_pago,
    respuesta_preferencia,
)
from atencion.tests.test_turnos import AHORA, MANANA_10

URL_MIS_PAGOS = reverse('pagos:lista')
URL_RETORNO = reverse('pagos:retorno')


class PagosVistasBase(PagosBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.usuario_clinico = User.objects.create_user(username='laura')
        cls.clinico.usuario = cls.usuario_clinico
        cls.clinico.save()
        cls.usuario_cardio = User.objects.create_user(username='federico')
        cls.cardiologo.usuario = cls.usuario_cardio
        cls.cardiologo.save()

    def setUp(self):
        super().setUp()
        parche = patch(
            'clinica.services.mascotas._hoy', return_value=AHORA.date(),
        )
        parche.start()
        self.addCleanup(parche.stop)
        self.client.force_login(self.ana.usuario)

    def pago_con_cobertura(self, **cambios):
        """Pago de Ana con VetSalud (70%): $15.000 - $10.500 = $4.500."""
        self.afiliar(self.ana, self.vetsalud, self.clinico)
        return self.pago(self.reservar(**cambios))

    def url(self, nombre, pago):
        return reverse(f'pagos:{nombre}', args=[pago.pk])


class ConfirmacionTests(PagosVistasBase):

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_muestra_precio_cobertura_monto_y_dos_opciones(self):
        pago = self.pago_con_cobertura()

        response = self.client.get(self.url('confirmacion', pago))

        self.assertContains(response, '$15.000')
        self.assertContains(response, '- $10.500')
        self.assertRegex(
            response.content.decode(), r'id="monto-a-pagar">\s*\$4\.500',
        )
        self.assertContains(response, 'Realizar pago')
        self.assertContains(response, f'action="{self.url("pagar", pago)}"')
        self.assertContains(
            response, 'Pagar en la clínica el día de la atención',
        )

    def test_muestra_el_motivo_sin_cobertura(self):
        pago = self.pago(self.reservar())

        response = self.client.get(self.url('confirmacion', pago))

        self.assertContains(response, 'Sin obra social')
        self.assertContains(response, '$15.000')

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_cubierto_por_la_obra_social_no_ofrece_pagar(self):
        self.afiliar(self.ana, self.huellitas, self.clinico)
        pago = self.pago(self.reservar())

        response = self.client.get(self.url('confirmacion', pago))

        self.assertContains(response, 'Cubierto por tu obra social')
        self.assertNotContains(response, 'Realizar pago')
        self.assertNotContains(response, 'Pagar en la clínica')

    def test_pagar_en_la_clinica_lleva_a_mis_consultas(self):
        pago = self.pago(self.reservar())

        response = self.client.get(self.url('en_clinica', pago), follow=True)

        self.assertRedirects(response, reverse('atencion:consultas'))
        self.assertContains(
            response,
            'Turno reservado. Podés pagarlo en la clínica el día de la '
            'atención o más tarde desde Mis pagos.',
        )
        self.assertEqual(self.pago(pago.turno).estado, Pago.Estado.PENDIENTE)

    def test_sacar_turno_lleva_a_la_confirmacion_del_pago(self):
        self.afiliar(self.ana, self.vetsalud, self.clinico)

        response = self.client.post(reverse('atencion:turno_confirmar'), {
            'mascota': self.firulais.pk,
            'especialidad': 'CLINICA_GENERAL',
            'veterinario': self.clinico.pk,
            'fecha_hora': MANANA_10.isoformat(),
        }, follow=True)

        pago = Pago.objects.get()
        self.assertRedirects(response, self.url('confirmacion', pago))
        self.assertContains(response, '$4.500')


class PagarTests(PagosVistasBase):

    def setUp(self):
        super().setUp()
        parche = patch(SDK)
        self.SDK = parche.start()
        self.addCleanup(parche.stop)
        self.crear = self.SDK.return_value.preference.return_value.create
        self.crear.return_value = respuesta_preferencia()

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_redirige_a_mercado_pago(self):
        pago = self.pago_con_cobertura()

        response = self.client.post(self.url('pagar', pago))

        self.assertRedirects(
            response,
            respuesta_preferencia()['response']['sandbox_init_point'],
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.crear.call_args.args[0]['items'][0]['unit_price'], 4500.0,
        )

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_get_no_esta_permitido(self):
        pago = self.pago_con_cobertura()

        self.assertEqual(self.client.get(self.url('pagar', pago)).status_code,
                         405)
        self.crear.assert_not_called()

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_pago_ajeno_da_404(self):
        pago_beto = self.pago(self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
        ))

        response = self.client.post(self.url('pagar', pago_beto))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.client.get(self.url('confirmacion', pago_beto)).status_code,
            404,
        )
        self.crear.assert_not_called()

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_pagado_cubierto_o_pasado_da_error(self):
        pagado = self.pago(self.reservar())
        registrar_cobro_efectivo(self.clinico, pagado.pk)
        pasado = self.pago(
            self.reservar(fecha_hora=MANANA_10.replace(hour=11)),
        )
        pasado.turno.fecha_hora = AHORA - timedelta(days=1)
        pasado.turno.save()
        self.afiliar(self.ana, self.huellitas, self.clinico)
        cubierto = self.pago(self.reservar(
            fecha_hora=MANANA_10.replace(hour=12),
        ))
        for pago, mensaje in (
            (pagado, 'ya está pagado'),
            (pasado, 'ya pasó'),
            (cubierto, 'cubierto por tu obra social'),
        ):
            with self.subTest(estado=pago.estado):
                response = self.client.post(
                    self.url('pagar', pago), follow=True,
                )
                self.assertRedirects(response, self.url('confirmacion', pago))
                self.assertContains(response, mensaje)
        self.crear.assert_not_called()

    @override_settings(MP_ACCESS_TOKEN='')
    def test_sin_credenciales_ofrece_pagar_en_la_clinica(self):
        pago = self.pago_con_cobertura()

        response = self.client.post(self.url('pagar', pago), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.url('confirmacion', pago))
        self.assertContains(response, 'El pago online no está disponible')
        self.assertContains(response, 'Pagar en la clínica')
        self.assertNotContains(response, 'Realizar pago')
        self.SDK.assert_not_called()

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_si_mercado_pago_no_responde_no_hay_error_500(self):
        pago = self.pago_con_cobertura()
        self.crear.side_effect = ConnectionError('caido')

        with self.assertLogs('administracion.services.mercadopago_service',
                             'ERROR'):
            response = self.client.post(self.url('pagar', pago), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Podés pagar en la clínica')


@override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
class RetornoTests(PagosVistasBase):

    def setUp(self):
        super().setUp()
        parche = patch(SDK)
        self.SDK = parche.start()
        self.addCleanup(parche.stop)
        self.obtener = self.SDK.return_value.payment.return_value.get
        self.pago_ana = self.pago_con_cobertura()

    def test_aprobado_muestra_el_comprobante(self):
        self.obtener.return_value = respuesta_pago(self.pago_ana)

        response = self.client.get(URL_RETORNO, {
            'payment_id': '987654321', 'status': 'approved',
            'external_reference': self.pago_ana.pk,
        })

        self.assertContains(response, '¡Pago aprobado!')
        self.assertContains(response, self.url('comprobante', self.pago_ana))
        self.assertEqual(Pago.objects.get(pk=self.pago_ana.pk).estado,
                         Pago.Estado.PAGADO)

    def test_no_confia_en_los_parametros_de_la_url(self):
        self.obtener.return_value = respuesta_pago(
            self.pago_ana, status='rejected',
        )

        response = self.client.get(URL_RETORNO, {
            'payment_id': '987654321', 'status': 'approved',
            'collection_status': 'approved',
        })

        self.assertContains(response, 'El pago no se completó')
        self.assertContains(response, 'Reintentar el pago')
        self.assertContains(response, 'Pagar en la clínica')
        self.assertEqual(Pago.objects.get(pk=self.pago_ana.pk).estado,
                         Pago.Estado.PENDIENTE)

    def test_pendiente(self):
        self.obtener.return_value = respuesta_pago(
            self.pago_ana, status='in_process',
        )

        response = self.client.get(URL_RETORNO, {'payment_id': '1'})

        self.assertContains(response, 'Pago pendiente')

    def test_sin_pago_vuelve_con_la_opcion_de_reintentar(self):
        response = self.client.get(URL_RETORNO, {
            'collection_id': 'null', 'external_reference': self.pago_ana.pk,
        })

        self.assertContains(response, 'El pago no se completó')
        self.assertContains(response, 'Reintentar el pago')
        self.obtener.assert_not_called()

    def test_pago_de_otro_dueno_da_404(self):
        pago_beto = self.pago(self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
            fecha_hora=MANANA_10.replace(hour=11),
        ))
        self.obtener.return_value = respuesta_pago(pago_beto)

        response = self.client.get(URL_RETORNO, {'payment_id': '1'})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Pago.objects.get(pk=pago_beto.pk).estado,
                         Pago.Estado.PENDIENTE)


class MisPagosYComprobanteTests(PagosVistasBase):

    @override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
    def test_mis_pagos_lista_pendientes_e_historial(self):
        pendiente = self.pago_con_cobertura()
        pagado = self.pago(
            self.reservar(fecha_hora=MANANA_10.replace(hour=11)),
        )
        registrar_cobro_efectivo(self.clinico, pagado.pk)

        response = self.client.get(URL_MIS_PAGOS)

        self.assertEqual(list(response.context['pendientes']), [pendiente])
        self.assertEqual(
            [p.pk for p in response.context['historial']], [pagado.pk],
        )
        self.assertContains(
            response, f'action="{self.url("pagar", pendiente)}"',
        )
        self.assertContains(response, f'CV-{pagado.pk:06d}')
        self.assertContains(response, f'href="{URL_MIS_PAGOS}"')  # menu

    def test_comprobante(self):
        pago = self.pago_con_cobertura()
        registrar_cobro_efectivo(self.clinico, pago.pk)

        response = self.client.get(self.url('comprobante', pago))

        self.assertContains(response, f'CV-{pago.pk:06d}')
        self.assertContains(response, 'Efectivo')
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Dra. Laura Fernández')
        self.assertContains(response, '$10.500')
        self.assertContains(response, 'Monto pagado')
        self.assertContains(response, 'window.print()')
        self.assertContains(response, '@media print')

    def test_comprobante_de_pago_sin_pagar_o_ajeno_da_404(self):
        pendiente = self.pago(self.reservar())
        pago_beto = self.pago(self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
            fecha_hora=MANANA_10.replace(hour=11),
        ))
        registrar_cobro_efectivo(self.clinico, pago_beto.pk)
        for pago in (pendiente, pago_beto):
            with self.subTest(pago=pago.pk):
                response = self.client.get(self.url('comprobante', pago))
                self.assertEqual(response.status_code, 404)

    def test_mis_consultas_muestra_monto_estado_y_pagar(self):
        pago = self.pago_con_cobertura()

        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, 'A pagar: <strong>$4.500</strong>')
        self.assertContains(response, 'Pago: Pendiente')
        self.assertContains(response, f'action="{self.url("pagar", pago)}"')

    def test_mi_perfil_muestra_el_tope_restante(self):
        self.pago_con_cobertura()

        response = self.client.get(reverse('clinica:perfil'))

        self.assertRegex(
            response.content.decode(),
            r'Te quedan <strong>\$39\.500</strong>',
        )

    def test_cancelar_un_turno_pagado_avisa_la_devolucion(self):
        pago = self.pago(self.reservar())
        registrar_cobro_efectivo(self.clinico, pago.pk)

        response = self.client.post(
            reverse('atencion:turno_cancelar', args=[pago.turno.pk]),
            follow=True,
        )

        self.assertContains(response, 'gestionar la devolución')
        self.assertEqual(self.pago(pago.turno).estado,
                         Pago.Estado.REEMBOLSADO)


class CobroEnClinicaTests(PagosVistasBase):

    def url_cobrar(self, pago):
        return reverse('veterinario:cobrar', args=[pago.turno.pk, pago.pk])

    def test_el_detalle_del_turno_muestra_el_pago_y_el_boton(self):
        pago = self.pago_con_cobertura()
        self.client.force_login(self.usuario_clinico)

        response = self.client.get(
            reverse('veterinario:turno', args=[pago.turno.pk]),
        )

        self.assertContains(response, '$15.000')
        self.assertContains(response, '- $10.500')
        self.assertContains(response, 'Pendiente')
        self.assertContains(response, 'Registrar cobro en efectivo')
        self.assertContains(response, 'confirm(')

    def test_el_veterinario_del_turno_registra_el_cobro(self):
        pago = self.pago_con_cobertura()
        self.client.force_login(self.usuario_clinico)

        response = self.client.post(self.url_cobrar(pago), follow=True)

        self.assertRedirects(
            response, reverse('veterinario:turno', args=[pago.turno.pk]),
        )
        self.assertContains(response, f'Comprobante CV-{pago.pk:06d}')
        self.assertNotContains(response, 'Registrar cobro en efectivo')
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PAGADO)
        self.assertEqual(pago.metodo, Pago.Metodo.EFECTIVO)

    def test_otro_veterinario_no_puede(self):
        pago = self.pago_con_cobertura()
        self.client.force_login(self.usuario_cardio)

        response = self.client.post(self.url_cobrar(pago))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.pago(pago.turno).estado, Pago.Estado.PENDIENTE)

    def test_un_dueno_no_puede(self):
        pago = self.pago_con_cobertura()

        response = self.client.post(self.url_cobrar(pago))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.pago(pago.turno).estado, Pago.Estado.PENDIENTE)

    def test_veterinario_no_entra_a_mis_pagos(self):
        self.client.force_login(self.usuario_clinico)

        self.assertEqual(self.client.get(URL_MIS_PAGOS).status_code, 403)
