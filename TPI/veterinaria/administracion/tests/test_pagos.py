"""Pagos (RF07): cobertura, montos fijos, Mercado Pago (SDK mockeado),
cobro en efectivo y cancelacion. "Hoy" es el miercoles 14/10/2026 a las
12:00 (TurnosBase congela timezone.now)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import RequestFactory, override_settings

from administracion.models import Pago
from administracion.services import mercadopago_service as mp
from administracion.services.pagos import (
    CONSULTA,
    GUARDIA,
    SERVICIO_NO_CUBIERTO,
    SIN_OBRA_SOCIAL,
    TOPE_ALCANZADO,
    VACUNACION,
    VETERINARIO_NO_ATIENDE,
    PagoError,
    PagoNoEncontrado,
    calcular_cobertura,
    cobertura_usada_en_mes,
    pagos_del_dueno,
    registrar_cobro_efectivo,
    tipo_servicio,
    tope_restante_del_mes,
)
from administracion.tests.test_obras_sociales import crear_obras_sociales
from atencion.models import PrecioVeterinario
from atencion.services.turnos import (
    cancelar_turno,
    reservar_turno_de_consulta,
)
from atencion.services.urgencias import (
    confirmar_turno_de_guardia,
    plan_de_urgencia,
)
from atencion.tests.test_turnos import (
    AHORA,
    MANANA_10,
    ZONA,
    TurnosBase,
    crear_veterinario,
)
from clinica.models import Vacuna
from clinica.services.vacunas import (
    cargar_vacunas_iniciales,
    reservar_turno_vacuna,
)

TOKEN_PRUEBA = 'TEST-1234567890'
SDK = 'administracion.services.mercadopago_service.mercadopago.SDK'
NOVIEMBRE_2 = datetime(2026, 11, 2, 10, 0, tzinfo=ZONA)  # lunes
URL_MP = 'https://www.mercadopago.com.ar/checkout/v1/redirect'
URL_MP_SANDBOX = 'https://sandbox.mercadopago.com.ar/checkout/v1/redirect'


class PagosBase(TurnosBase):
    """Precios por especialidad: clinica general $15.000, guardia
    $30.000, vacunacion $12.000.

    Obras sociales: VetSalud Plus 70% (tope $50.000, cubre todo),
    Mascotas Protegidas 50% (tope $20.000, consultas y vacunacion),
    PetCare Básico 30% (tope $10.000, solo vacunacion) y Huellitas Total
    100% (tope $80.000, cubre todo)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.obras, _ = crear_obras_sociales()
        cls.vetsalud = cls.obras['VetSalud Plus']
        cls.protegidas = cls.obras['Mascotas Protegidas']
        cls.petcare = cls.obras['PetCare Básico']
        cls.huellitas = cls.obras['Huellitas Total']
        cls.guardia = crear_veterinario(
            'Dra. Luciana Paz', 'MP-5025', 'GUARDIA',
            time(0, 0), time(23, 30), dias=range(7),
        )
        cls.vacunador = crear_veterinario(
            'Dra. Paula Navarro', 'MP-5019', 'VACUNACION',
            time(8, 0), time(13, 0),
        )
        cargar_vacunas_iniciales()
        cls.sextuple = Vacuna.objects.get(nombre='Séxtuple')

    def afiliar(self, dueno, obra_social, *veterinarios):
        """El dueño tiene la obra social y los veterinarios la atienden."""
        dueno.obra_social = obra_social
        dueno.numero_afiliado = 'A-1' if obra_social else ''
        dueno.save()
        for veterinario in veterinarios:
            veterinario.obras_sociales.add(obra_social)

    def pago(self, turno):
        return Pago.objects.get(turno=turno)


class TipoServicioTests(PagosBase):

    def test_clasifica_guardia_vacunacion_y_consulta(self):
        consulta = self.reservar()
        vacuna = reservar_turno_vacuna(
            self.ana, self.firulais.pk, self.sextuple.pk,
            self.vacunador.pk, MANANA_10,
        )
        guardia = self.reservar(
            veterinario_id=self.guardia.pk, fecha_hora=MANANA_10,
            tipo='Guardia',
        )

        self.assertEqual(tipo_servicio(consulta), CONSULTA)
        self.assertEqual(tipo_servicio(vacuna), VACUNACION)
        self.assertEqual(tipo_servicio(guardia), GUARDIA)


class CoberturaTests(PagosBase):

    def test_sin_obra_social_no_cubre(self):
        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_total, Decimal('15000'))
        self.assertEqual(pago.monto_cubierto_os, 0)
        self.assertEqual(pago.monto_a_pagar, Decimal('15000'))
        self.assertEqual(pago.detalle_cobertura, SIN_OBRA_SOCIAL)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_veterinario_que_no_atiende_la_obra_social(self):
        self.afiliar(self.ana, self.vetsalud, self.cardiologo)

        pago = self.pago(self.reservar())  # con el clinico

        self.assertEqual(pago.monto_cubierto_os, 0)
        self.assertEqual(pago.monto_a_pagar, Decimal('15000'))
        self.assertEqual(pago.detalle_cobertura, VETERINARIO_NO_ATIENDE)

    def test_obra_social_que_no_cubre_el_servicio(self):
        self.afiliar(self.ana, self.petcare, self.clinico)

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_cubierto_os, 0)
        self.assertEqual(pago.detalle_cobertura, SERVICIO_NO_CUBIERTO)

    def test_cubre_el_porcentaje(self):
        self.afiliar(self.ana, self.vetsalud, self.clinico)

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_cubierto_os, Decimal('10500'))
        self.assertEqual(pago.monto_a_pagar, Decimal('4500'))
        self.assertEqual(pago.detalle_cobertura, '')
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_cien_por_ciento_queda_cubierto_por_la_obra_social(self):
        self.afiliar(self.ana, self.huellitas, self.clinico)

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_cubierto_os, Decimal('15000'))
        self.assertEqual(pago.monto_a_pagar, 0)
        self.assertEqual(pago.estado, Pago.Estado.CUBIERTO_OS)

    def _cobertura_previa(self, monto, fecha_hora=MANANA_10,
                          estado=Pago.Estado.PENDIENTE):
        """Un pago anterior del dueño que ya uso `monto` del tope."""
        turno = self.reservar(fecha_hora=fecha_hora)
        Pago.objects.filter(turno=turno).update(
            monto_cubierto_os=monto, estado=estado,
        )
        return turno

    def test_tope_parcialmente_usado_limita_la_cobertura(self):
        self.afiliar(self.ana, self.protegidas, self.clinico)
        self._cobertura_previa(Decimal('18000'))

        pago = self.pago(self.reservar(fecha_hora=MANANA_10.replace(hour=11)))

        # 50% de 15.000 = 7.500, pero solo quedan 2.000 del tope.
        self.assertEqual(pago.monto_cubierto_os, Decimal('2000'))
        self.assertEqual(pago.monto_a_pagar, Decimal('13000'))
        self.assertEqual(pago.detalle_cobertura, '')

    def test_tope_agotado_no_cubre(self):
        self.afiliar(self.ana, self.protegidas, self.clinico)
        self._cobertura_previa(Decimal('20000'), estado=Pago.Estado.PAGADO)

        pago = self.pago(self.reservar(fecha_hora=MANANA_10.replace(hour=11)))

        self.assertEqual(pago.monto_cubierto_os, 0)
        self.assertEqual(pago.monto_a_pagar, Decimal('15000'))
        self.assertEqual(pago.detalle_cobertura, TOPE_ALCANZADO)

    def test_otro_mes_y_cancelados_no_cuentan_para_el_tope(self):
        self.afiliar(self.ana, self.protegidas, self.clinico)
        self._cobertura_previa(Decimal('20000'), fecha_hora=NOVIEMBRE_2)
        for estado in (Pago.Estado.CANCELADO, Pago.Estado.REEMBOLSADO):
            self._cobertura_previa(
                Decimal('20000'), estado=estado,
                fecha_hora=MANANA_10.replace(
                    hour=11 if estado == 'CANCELADO' else 12,
                ),
            )

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_cubierto_os, Decimal('7500'))
        self.assertEqual(cobertura_usada_en_mes(self.ana, 2026, 10),
                         Decimal('7500'))
        self.assertEqual(cobertura_usada_en_mes(self.ana, 2026, 11),
                         Decimal('20000'))

    def test_pagos_de_otro_dueno_no_cuentan(self):
        self.afiliar(self.ana, self.protegidas, self.clinico)
        self.afiliar(self.beto, self.protegidas)
        turno_beto = self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
            fecha_hora=MANANA_10.replace(hour=11),
        )
        Pago.objects.filter(turno=turno_beto).update(
            monto_cubierto_os=Decimal('20000'),
        )

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_cubierto_os, Decimal('7500'))

    def test_tope_restante_del_mes(self):
        self.assertIsNone(tope_restante_del_mes(self.ana))
        self.afiliar(self.ana, self.protegidas, self.clinico)
        self.reservar()

        self.assertEqual(tope_restante_del_mes(self.ana), Decimal('12500'))

    def test_calcular_cobertura_devuelve_el_motivo(self):
        turno = self.reservar()
        self.afiliar(self.ana, self.vetsalud, self.clinico)

        self.assertEqual(
            calcular_cobertura(self.ana, turno, Decimal('10000')),
            (Decimal('7000'), Decimal('3000'), None),
        )


class MontosFijosTests(PagosBase):

    def test_usa_el_precio_vigente_del_veterinario(self):
        PrecioVeterinario.objects.create(
            veterinario=self.clinico, monto=Decimal('20000'),
            vigente_desde=date(2026, 1, 1),
        )
        self.afiliar(self.ana, self.vetsalud, self.clinico)

        pago = self.pago(self.reservar())

        self.assertEqual(pago.monto_total, Decimal('20000'))
        self.assertEqual(pago.monto_cubierto_os, Decimal('14000'))
        self.assertEqual(pago.monto_a_pagar, Decimal('6000'))

    def test_cambios_posteriores_no_modifican_el_pago(self):
        self.afiliar(self.ana, self.vetsalud, self.clinico)
        turno = self.reservar()

        self.ana.obra_social = None
        self.ana.save()
        self.clinico.obras_sociales.clear()
        PrecioVeterinario.objects.create(
            veterinario=self.clinico, monto=Decimal('99000'),
            vigente_desde=date(2026, 1, 1),
        )
        self.vetsalud.porcentaje_cobertura = 10
        self.vetsalud.save()

        pago = self.pago(turno)
        self.assertEqual(pago.monto_total, Decimal('15000'))
        self.assertEqual(pago.monto_cubierto_os, Decimal('10500'))
        self.assertEqual(pago.monto_a_pagar, Decimal('4500'))


class FlujosDeReservaTests(PagosBase):

    def test_sacar_turno(self):
        self.afiliar(self.ana, self.vetsalud, self.clinico)

        turno = reservar_turno_de_consulta(
            self.ana, self.firulais.pk, 'CLINICA_GENERAL', self.clinico.pk,
            MANANA_10,
        )

        pago = self.pago(turno)
        self.assertEqual(pago.monto_cubierto_os, Decimal('10500'))
        self.assertEqual(pago.monto_a_pagar, Decimal('4500'))

    def test_vacunacion(self):
        self.afiliar(self.ana, self.petcare, self.vacunador)

        turno = reservar_turno_vacuna(
            self.ana, self.firulais.pk, self.sextuple.pk,
            self.vacunador.pk, MANANA_10,
        )

        pago = self.pago(turno)
        self.assertEqual(pago.monto_total, Decimal('12000'))
        self.assertEqual(pago.monto_cubierto_os, Decimal('3600'))
        self.assertEqual(pago.monto_a_pagar, Decimal('8400'))

    def test_urgencia_alta_confirmada(self):
        self.afiliar(self.ana, self.vetsalud, self.guardia)
        libre = AHORA + timedelta(hours=1)

        turno = confirmar_turno_de_guardia(
            self.ana, self.firulais.pk, self.guardia.pk, libre.isoformat(),
        )

        pago = self.pago(turno)
        self.assertEqual(pago.monto_total, Decimal('30000'))
        self.assertEqual(pago.monto_cubierto_os, Decimal('21000'))
        self.assertEqual(pago.monto_a_pagar, Decimal('9000'))

    def test_urgencia_critica_reservada_sola(self):
        self.afiliar(self.ana, self.protegidas, self.guardia)

        plan = plan_de_urgencia(self.ana, self.firulais, 'CRITICA')

        pago = self.pago(plan['turno'])
        self.assertEqual(pago.monto_cubierto_os, 0)
        self.assertEqual(pago.detalle_cobertura, SERVICIO_NO_CUBIERTO)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)


def respuesta_preferencia(status=201):
    return {'status': status, 'response': {
        'id': 'pref-123',
        'init_point': URL_MP + '?pref_id=pref-123',
        'sandbox_init_point': URL_MP_SANDBOX + '?pref_id=pref-123',
    }}


def respuesta_pago(pago, status='approved', monto=None, referencia=None,
                   payment_id=987654321):
    return {'status': 200, 'response': {
        'id': payment_id,
        'status': status,
        'external_reference': (
            str(pago.pk) if referencia is None else referencia
        ),
        'transaction_amount': float(
            pago.monto_a_pagar if monto is None else monto
        ),
    }}


@override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
class CrearPreferenciaTests(PagosBase):

    def setUp(self):
        super().setUp()
        self.afiliar(self.ana, self.vetsalud, self.clinico)
        self.pago_ana = self.pago(self.reservar())  # $4.500 a pagar
        parche = patch(SDK)
        self.SDK = parche.start()
        self.addCleanup(parche.stop)
        self.crear = self.SDK.return_value.preference.return_value.create
        self.crear.return_value = respuesta_preferencia()

    def _request(self, **extra):
        return RequestFactory().get('/', **extra)

    def test_envia_monto_a_pagar_y_referencia(self):
        url = mp.crear_preferencia(self.pago_ana, self._request())

        self.SDK.assert_called_once()
        self.assertEqual(self.SDK.call_args.args[0], TOKEN_PRUEBA)
        datos = self.crear.call_args.args[0]
        self.assertEqual(datos['external_reference'], str(self.pago_ana.pk))
        self.assertEqual(datos['items'][0]['unit_price'], 4500.0)
        self.assertEqual(datos['items'][0]['quantity'], 1)
        self.assertEqual(datos['items'][0]['currency_id'], 'ARS')
        self.assertEqual(
            datos['items'][0]['title'],
            'Consulta de Firulais con Dra. Laura Fernández - '
            '15/10/2026 10:00',
        )
        for clave in ('success', 'failure', 'pending'):
            self.assertEqual(
                datos['back_urls'][clave],
                'http://testserver/cuenta/pagos/retorno/',
            )
        # localhost / http: sin auto_return.
        self.assertNotIn('auto_return', datos)
        self.assertIn('sandbox.mercadopago', url)
        self.pago_ana.refresh_from_db()
        self.assertEqual(self.pago_ana.mp_preference_id, 'pref-123')

    @override_settings(MP_ACCESS_TOKEN='APP_USR-123')
    def test_con_credenciales_de_usuario_de_prueba_usa_init_point(self):
        url = mp.crear_preferencia(self.pago_ana, self._request())

        self.assertTrue(url.startswith('https://www.mercadopago.com.ar/'))

    @override_settings(ALLOWED_HOSTS=['clinicavet24.com.ar'])
    def test_con_https_publico_usa_auto_return(self):
        mp.crear_preferencia(self.pago_ana, self._request(
            secure=True, HTTP_HOST='clinicavet24.com.ar',
        ))

        datos = self.crear.call_args.args[0]
        self.assertEqual(datos['auto_return'], 'approved')
        self.assertEqual(
            datos['back_urls']['success'],
            'https://clinicavet24.com.ar/cuenta/pagos/retorno/',
        )

    @override_settings(ALLOWED_HOSTS=['clinicavet24.com.ar'])
    def test_si_rechaza_auto_return_reintenta_sin_el(self):
        self.crear.side_effect = [
            {'status': 400, 'response': {'message': 'auto_return invalid'}},
            respuesta_preferencia(),
        ]

        mp.crear_preferencia(self.pago_ana, self._request(
            secure=True, HTTP_HOST='clinicavet24.com.ar',
        ))

        self.assertEqual(self.crear.call_count, 2)
        self.assertNotIn('auto_return', self.crear.call_args.args[0])

    def test_si_mercado_pago_falla_lanza_error(self):
        for efecto in (
            {'status': 500, 'response': {}},
            ConnectionError('sin red'),
        ):
            with self.subTest(efecto=efecto):
                self.crear.side_effect = (
                    efecto if isinstance(efecto, Exception) else None
                )
                self.crear.return_value = efecto
                with (
                    self.assertRaises(mp.MercadoPagoError),
                    self.assertLogs(mp.logger, 'ERROR'),
                ):
                    mp.crear_preferencia(self.pago_ana, self._request())

    @override_settings(MP_ACCESS_TOKEN='')
    def test_sin_credenciales_no_llama_a_la_api(self):
        with self.assertRaises(mp.MercadoPagoError) as error:
            mp.crear_preferencia(self.pago_ana, self._request())

        self.assertIn('pagar en la clínica', str(error.exception))
        self.SDK.assert_not_called()

    def test_no_se_puede_pagar_online_si_no_corresponde(self):
        turno_pasado = self.reservar(fecha_hora=MANANA_10.replace(hour=11))
        pasado = self.pago(turno_pasado)
        turno_pasado.fecha_hora = AHORA - timedelta(days=1)
        turno_pasado.save()
        self.afiliar(self.ana, self.huellitas, self.clinico)
        cubierto = self.pago(self.reservar(
            fecha_hora=MANANA_10.replace(hour=12),
        ))
        pagado = self.pago(self.reservar(
            fecha_hora=MANANA_10.replace(hour=13),
        ))
        Pago.objects.filter(pk=pagado.pk).update(
            estado=Pago.Estado.PAGADO, monto_a_pagar=100,
        )
        for pago in (Pago.objects.get(pk=pasado.pk), cubierto,
                     Pago.objects.get(pk=pagado.pk)):
            with self.subTest(pago=pago):
                with self.assertRaises(PagoError):
                    mp.crear_preferencia(pago, self._request())
        self.crear.assert_not_called()


@override_settings(MP_ACCESS_TOKEN=TOKEN_PRUEBA)
class VerificarPagoTests(PagosBase):

    def setUp(self):
        super().setUp()
        self.afiliar(self.ana, self.vetsalud, self.clinico)
        self.pago_ana = self.pago(self.reservar())  # $4.500 a pagar
        parche = patch(SDK)
        self.SDK = parche.start()
        self.addCleanup(parche.stop)
        self.obtener = self.SDK.return_value.payment.return_value.get

    def test_aprobado_marca_pagado_con_comprobante(self):
        self.obtener.return_value = respuesta_pago(self.pago_ana)

        resultado, pago = mp.verificar_y_registrar_pago('987654321', self.ana)

        self.obtener.assert_called_once_with('987654321')
        self.assertEqual(resultado, mp.APROBADO)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PAGADO)
        self.assertEqual(pago.metodo, Pago.Metodo.MERCADO_PAGO)
        self.assertEqual(pago.mp_payment_id, '987654321')
        self.assertEqual(pago.fecha_pago, AHORA)
        self.assertEqual(pago.numero_comprobante, f'CV-{pago.pk:06d}')

    def test_llamarlo_dos_veces_no_duplica_nada(self):
        self.obtener.return_value = respuesta_pago(self.pago_ana)
        mp.verificar_y_registrar_pago('987654321')
        primero = Pago.objects.get(pk=self.pago_ana.pk)

        resultado, _ = mp.verificar_y_registrar_pago('987654321')

        segundo = Pago.objects.get(pk=self.pago_ana.pk)
        self.assertEqual(resultado, mp.APROBADO)
        self.assertEqual(segundo.numero_comprobante,
                         primero.numero_comprobante)
        self.assertEqual(segundo.fecha_pago, primero.fecha_pago)
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(
            Pago.objects.exclude(numero_comprobante=None).count(), 1,
        )

    def test_comprobantes_unicos(self):
        otro = self.pago(self.reservar(fecha_hora=MANANA_10.replace(hour=11)))
        for pago, payment_id in ((self.pago_ana, 1), (otro, 2)):
            self.obtener.return_value = respuesta_pago(
                pago, payment_id=payment_id,
            )
            mp.verificar_y_registrar_pago(str(payment_id))

        numeros = set(Pago.objects.values_list('numero_comprobante',
                                               flat=True))
        self.assertEqual(len(numeros), 2)

    def test_rechazado_o_pendiente_sigue_pendiente(self):
        for status, esperado in (
            ('rejected', mp.RECHAZADO),
            ('cancelled', mp.RECHAZADO),
            ('pending', mp.PENDIENTE),
            ('in_process', mp.PENDIENTE),
        ):
            with self.subTest(status=status):
                self.obtener.return_value = respuesta_pago(
                    self.pago_ana, status=status,
                )
                resultado, _ = mp.verificar_y_registrar_pago('1')
                self.assertEqual(resultado, esperado)
                self.assertEqual(
                    Pago.objects.get(pk=self.pago_ana.pk).estado,
                    Pago.Estado.PENDIENTE,
                )

    def test_monto_distinto_no_se_marca(self):
        self.obtener.return_value = respuesta_pago(
            self.pago_ana, monto=Decimal('1'),
        )

        with self.assertRaises(PagoError):
            mp.verificar_y_registrar_pago('1')

        self.assertEqual(Pago.objects.get(pk=self.pago_ana.pk).estado,
                         Pago.Estado.PENDIENTE)

    def test_referencia_que_no_coincide_no_se_marca(self):
        turno_beto = self.reservar(
            dueno=self.beto, mascota_id=self.michi.pk,
            fecha_hora=MANANA_10.replace(hour=11),
        )
        pago_beto = self.pago(turno_beto)
        casos = (
            ('9999', PagoNoEncontrado, None),
            ('abc', PagoError, None),
            (str(pago_beto.pk), PagoNoEncontrado, self.ana),
        )
        for referencia, error, dueno in casos:
            with self.subTest(referencia=referencia):
                self.obtener.return_value = respuesta_pago(
                    self.pago_ana, referencia=referencia,
                )
                with self.assertRaises(error):
                    mp.verificar_y_registrar_pago('1', dueno)
        self.assertFalse(
            Pago.objects.filter(estado=Pago.Estado.PAGADO).exists(),
        )

    def test_payment_id_invalido_o_api_caida(self):
        with self.assertRaises(PagoError):
            mp.verificar_y_registrar_pago('null')
        self.obtener.return_value = {'status': 404, 'response': {}}
        with (
            self.assertRaises(mp.MercadoPagoError),
            self.assertLogs(mp.logger, 'ERROR'),
        ):
            mp.verificar_y_registrar_pago('1')
        self.obtener.side_effect = TimeoutError()
        with (
            self.assertRaises(mp.MercadoPagoError),
            self.assertLogs(mp.logger, 'ERROR'),
        ):
            mp.verificar_y_registrar_pago('1')


class CobroEfectivoTests(PagosBase):

    def test_el_veterinario_del_turno_lo_registra(self):
        pago = self.pago(self.reservar())

        registrar_cobro_efectivo(self.clinico, pago.pk)

        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PAGADO)
        self.assertEqual(pago.metodo, Pago.Metodo.EFECTIVO)
        self.assertEqual(pago.fecha_pago, AHORA)
        self.assertEqual(pago.numero_comprobante, f'CV-{pago.pk:06d}')

    def test_otro_veterinario_no_puede(self):
        pago = self.pago(self.reservar())

        with self.assertRaises(PagoNoEncontrado):
            registrar_cobro_efectivo(self.cardiologo, pago.pk)

        self.assertEqual(self.pago(pago.turno).estado, Pago.Estado.PENDIENTE)

    def test_solo_pendientes(self):
        pago = self.pago(self.reservar())
        registrar_cobro_efectivo(self.clinico, pago.pk)

        with self.assertRaises(PagoError):
            registrar_cobro_efectivo(self.clinico, pago.pk)


class CancelarTurnoTests(PagosBase):

    def test_pendiente_pasa_a_cancelado(self):
        turno = self.reservar()

        cancelar_turno(self.ana, turno.pk)

        self.assertEqual(self.pago(turno).estado, Pago.Estado.CANCELADO)

    def test_pagado_pasa_a_reembolsado(self):
        turno = self.reservar()
        registrar_cobro_efectivo(self.clinico, self.pago(turno).pk)

        cancelar_turno(self.ana, turno.pk)

        self.assertEqual(self.pago(turno).estado, Pago.Estado.REEMBOLSADO)

    def test_cubierto_por_obra_social_pasa_a_cancelado(self):
        self.afiliar(self.ana, self.huellitas, self.clinico)
        turno = self.reservar()

        cancelar_turno(self.ana, turno.pk)

        self.assertEqual(self.pago(turno).estado, Pago.Estado.CANCELADO)
        # Lo que cubria deja de contar para el tope.
        self.assertEqual(cobertura_usada_en_mes(self.ana, 2026, 10), 0)


class PagosDelDuenoTests(PagosBase):

    def test_pendientes_primero_y_despues_el_historial(self):
        lejano = self.reservar(fecha_hora=NOVIEMBRE_2)
        cercano = self.reservar()
        pagado = self.reservar(fecha_hora=MANANA_10.replace(hour=11))
        registrar_cobro_efectivo(self.clinico, self.pago(pagado).pk)
        self.reservar(dueno=self.beto, mascota_id=self.michi.pk,
                      fecha_hora=MANANA_10.replace(hour=12))

        pagos = pagos_del_dueno(self.ana)

        self.assertEqual(
            [p.turno for p in pagos['pendientes']], [cercano, lejano],
        )
        self.assertEqual([p.turno for p in pagos['historial']], [pagado])
