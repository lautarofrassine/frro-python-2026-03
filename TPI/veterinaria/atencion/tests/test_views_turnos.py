from unittest.mock import patch

from django.urls import reverse

from administracion.models import Pago
from atencion.models import Turno
from atencion.services.turnos import reservar_turno
from atencion.tests.test_turnos import AHORA, MANANA_10, TurnosBase


class TurnosViewsBase(TurnosBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana.usuario)


class ConfirmarTurnoDelTriageTests(TurnosViewsBase):

    def _post(self, **cambios):
        datos = {
            'mascota_id': self.firulais.pk,
            'nivel_urgencia': 'MEDIA',
            'fecha_hora_y_vet': f'{MANANA_10.isoformat()}|{self.clinico.pk}',
        }
        datos.update(cambios)
        return self.client.post(
            reverse('atencion:confirmar_turno'), datos, follow=True,
        )

    def test_reserva_el_turno_elegido_con_su_pago(self):
        response = self._post()

        self.assertTemplateUsed(response, 'atencion/turno_confirmado.html')
        turno = Turno.objects.get()
        self.assertEqual(turno.mascota, self.firulais)
        self.assertEqual(turno.fecha_hora, MANANA_10)
        self.assertEqual(turno.tipo, 'Consulta Regular')
        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'MEDIA')
        self.assertEqual(turno.pagos.get().estado, Pago.Estado.PENDIENTE)

    def test_mascota_de_otro_dueno_no_reserva(self):
        response = self._post(mascota_id=self.michi.pk)

        self.assertRedirects(response, reverse('atencion:triage'))
        self.assertContains(response, 'no está entre tus mascotas')
        self.assertEqual(Turno.objects.count(), 0)

    def test_horario_ya_reservado_avisa_y_no_duplica(self):
        reservar_turno(
            self.beto, self.michi.pk, self.clinico.pk, MANANA_10,
        )

        response = self._post()

        self.assertRedirects(response, reverse('atencion:triage'))
        self.assertContains(response, 'acaba de ser reservado')
        self.assertEqual(Turno.objects.count(), 1)
        self.assertEqual(Pago.objects.count(), 1)

    def test_seleccion_invalida_o_get_no_rompen(self):
        response = self._post(fecha_hora_y_vet='cualquier cosa')
        por_get = self.client.get(reverse('atencion:confirmar_turno'))

        self.assertRedirects(response, reverse('atencion:triage'))
        self.assertRedirects(por_get, reverse('atencion:triage'))
        self.assertEqual(Turno.objects.count(), 0)


@patch('clinica.services.mascotas._hoy', return_value=AHORA.date())
class TriageCriticoTests(TurnosViewsBase):

    def _post_critico(self):
        resultado = {
            'nivel': 'CRITICA', 'nivel_modelo': 'CRITICA',
            'regla_aplicada': None,
        }
        with patch('atencion.services.triage.clasificar_urgencia',
                   return_value=resultado):
            return self.client.post(reverse('atencion:triage'), {
                'mascota': self.firulais.pk,
                'dias_evolucion': '1',
                'temperatura': '',
            })

    def test_critica_reserva_solo_el_horario_mas_proximo(self, _hoy):
        response = self._post_critico()

        self.assertTemplateUsed(response, 'atencion/turno_confirmado.html')
        turno = Turno.objects.get()
        self.assertEqual(turno.fecha_hora, AHORA.replace(minute=30))
        self.assertEqual(turno.tipo, 'Triage')
        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'CRITICA')
        self.assertEqual(turno.pagos.count(), 1)

    def test_critica_sin_veterinarios_muestra_el_resultado_con_aviso(
        self, _hoy,
    ):
        self.clinico.estado = 'INACTIVO'
        self.clinico.save()
        self.cardiologo.estado = 'INACTIVO'
        self.cardiologo.save()

        response = self._post_critico()

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_resultado.html')
        self.assertContains(response, 'No hay veterinarios disponibles')
        self.assertEqual(Turno.objects.count(), 0)

    def test_resultado_no_critico_ofrece_los_horarios_libres(self, _hoy):
        resultado = {
            'nivel': 'MEDIA', 'nivel_modelo': 'MEDIA', 'regla_aplicada': None,
        }
        with patch('atencion.services.triage.clasificar_urgencia',
                   return_value=resultado):
            response = self.client.post(reverse('atencion:triage'), {
                'mascota': self.firulais.pk,
                'dias_evolucion': '1',
                'temperatura': '',
            })

        libres = response.context['turnos_libres']
        self.assertEqual(libres[0]['fecha_hora'], AHORA.replace(minute=30))
        self.assertContains(response, 'Dra. Laura Fernández')
        self.assertEqual(Turno.objects.count(), 0)


class CancelarTurnoViewTests(TurnosViewsBase):

    def setUp(self):
        super().setUp()
        self.turno = reservar_turno(
            self.ana, self.firulais.pk, self.clinico.pk, MANANA_10,
        )
        self.url = reverse('atencion:turno_cancelar', args=[self.turno.pk])

    def test_mis_consultas_muestra_el_boton_cancelar(self):
        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, self.url)
        self.assertContains(response, 'Cancelar turno')
        self.assertContains(response, 'Pago: Pendiente')

    def test_get_muestra_la_confirmacion_sin_cancelar(self):
        response = self.client.get(self.url)

        self.assertContains(
            response, '¿Seguro que querés cancelar el turno de',
        )
        self.assertContains(response, 'Firulais')
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.PENDIENTE)

    def test_post_cancela_y_vuelve_a_mis_consultas(self):
        response = self.client.post(self.url, follow=True)

        self.assertRedirects(response, reverse('atencion:consultas'))
        self.assertContains(response, 'Se canceló el turno de Firulais.')
        self.assertContains(response, 'No tenés turnos reservados')
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.CANCELADO)
        self.assertEqual(
            self.turno.pagos.get().estado, Pago.Estado.CANCELADO,
        )

    def test_post_vuelve_a_la_pagina_indicada_solo_si_es_del_sitio(self):
        interna = self.client.post(
            self.url, {'siguiente': '/cuenta/vacunas/?mascota=1'},
        )
        otro = reservar_turno(
            self.ana, self.firulais.pk, self.clinico.pk,
            MANANA_10.replace(hour=11),
        )
        externa = self.client.post(
            reverse('atencion:turno_cancelar', args=[otro.pk]),
            {'siguiente': 'https://sitio-malicioso.example/'},
        )

        self.assertRedirects(
            interna, '/cuenta/vacunas/?mascota=1',
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            externa, reverse('atencion:consultas'),
            fetch_redirect_response=False,
        )

    def test_turno_de_otro_dueno_da_404(self):
        self.client.force_login(self.beto.usuario)

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.PENDIENTE)

    def test_con_menos_de_dos_horas_no_hay_boton_ni_se_cancela(self):
        cercano = reservar_turno(
            self.ana, self.firulais.pk, self.clinico.pk,
            AHORA.replace(hour=13),
        )
        url = reverse('atencion:turno_cancelar', args=[cercano.pk])

        consultas = self.client.get(reverse('atencion:consultas'))
        por_get = self.client.get(url, follow=True)
        por_post = self.client.post(url, follow=True)

        self.assertNotContains(consultas, url)
        self.assertContains(por_get, 'ya no se puede cancelar')
        self.assertContains(por_post, '2 horas antes')
        cercano.refresh_from_db()
        self.assertEqual(cercano.estado, Turno.Estado.PENDIENTE)

    def test_sin_sesion_redirige_a_ingresar(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(
            response, f"{reverse('clinica:ingresar')}?next={self.url}",
        )
