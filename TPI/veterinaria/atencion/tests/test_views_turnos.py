import html
import re
from datetime import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from administracion.models import Pago
from atencion.models import Turno
from atencion.services.turnos import reservar_turno
from atencion.tests.test_turnos import (
    AHORA,
    MANANA_10,
    TurnosBase,
    crear_veterinario,
)
from clinica.tests.test_mascotas import crear_dueno

URL_NUEVO = reverse('atencion:turno_nuevo')
URL_CONFIRMAR = reverse('atencion:turno_confirmar')


class TurnosViewsBase(TurnosBase):

    def setUp(self):
        super().setUp()
        parche = patch(
            'clinica.services.mascotas._hoy', return_value=AHORA.date(),
        )
        parche.start()
        self.addCleanup(parche.stop)
        self.client.force_login(self.ana.usuario)


class SacarTurnoViewTests(TurnosViewsBase):

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

    def _paso_3(self, **parametros):
        datos = {'mascota': self.firulais.pk, 'especialidad': 'CARDIOLOGIA'}
        datos.update(parametros)
        return self.client.get(URL_NUEVO, datos)

    def _datos_confirmacion(self, **cambios):
        datos = {
            'mascota': self.firulais.pk,
            'especialidad': 'CLINICA_GENERAL',
            'veterinario': self.clinico.pk,
            'fecha_hora': MANANA_10.isoformat(),
        }
        datos.update(cambios)
        return datos

    def test_todo_el_flujo_requiere_sesion(self):
        self.client.logout()

        for url in (URL_NUEVO, URL_CONFIRMAR):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('clinica:ingresar')}?next={url}",
                )

    def test_paso_1_muestra_las_mascotas_del_dueno(self):
        response = self.client.get(URL_NUEVO)

        self.assertEqual(response.context['paso'], 1)
        self.assertContains(response, '1 Mascota')
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Mestizo')
        self.assertContains(response, '6 años y 5 meses')
        self.assertContains(response, 'fa-dog')
        self.assertContains(
            response, f'{URL_NUEVO}?mascota={self.firulais.pk}',
        )
        self.assertNotContains(response, 'Michi')

    def test_paso_1_sin_mascotas_ofrece_registrar_una(self):
        for usuario in (
            crear_dueno('carla@mail.com', '31555666', 'Carla').usuario,
            get_user_model().objects.create_user('admin', is_staff=True),
        ):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                response = self.client.get(URL_NUEVO)

                self.assertContains(response, 'Registrar mascota')
                self.assertContains(
                    response, reverse('clinica:mascota_nueva'),
                )

    def test_paso_2_no_lista_guardia_ni_vacunacion(self):
        response = self.client.get(URL_NUEVO, {'mascota': self.firulais.pk})

        self.assertEqual(response.context['paso'], 2)
        self.assertEqual(
            [e['codigo'] for e in response.context['especialidades']],
            ['CLINICA_GENERAL', 'CARDIOLOGIA'],
        )
        self.assertContains(response, 'Clínica general')
        self.assertContains(response, 'Cardiología')
        self.assertContains(response, '$15.000')
        self.assertContains(response, '$28.000')
        self.assertContains(response, 'Corazón y sistema circulatorio.')
        self.assertNotContains(response, 'Guardia')
        self.assertNotContains(response, 'Vacunación')

    def test_paso_3_muestra_solo_los_horarios_de_la_especialidad(self):
        response = self._paso_3()

        self.assertEqual(response.context['paso'], 3)
        semana = response.context['semana']
        veterinarios = {
            h['veterinario_id'] for d in semana['dias'] for h in d['horarios']
        }
        self.assertEqual(veterinarios, {self.cardiologo.pk})
        self.assertContains(response, 'Semana del 12 de octubre')
        self.assertContains(response, 'Sin turnos')
        self.assertContains(response, 'Acosta')
        self.assertContains(response, 'Dr. Federico Acosta')
        self.assertNotContains(response, 'Sosa')
        self.assertNotContains(response, 'Luciana Paz')
        self.assertNotContains(response, 'aria-label="Semana anterior"')
        self.assertContains(response, 'semana=2026-10-19')

    def test_paso_3_respeta_el_filtro_por_veterinario(self):
        todos = self._paso_3(especialidad='CLINICA_GENERAL')
        filtrado = self._paso_3(
            especialidad='CLINICA_GENERAL', veterinario=self.otro_clinico.pk,
        )

        self.assertIsNone(todos.context['semana']['veterinario'])
        self.assertContains(todos, 'Fernández')
        semana = filtrado.context['semana']
        self.assertEqual(semana['veterinario'], self.otro_clinico)
        self.assertEqual(
            {h['veterinario_id'] for d in semana['dias']
             for h in d['horarios']},
            {self.otro_clinico.pk},
        )

    def test_paso_3_no_muestra_los_horarios_ocupados(self):
        reservar_turno(
            self.beto, self.michi.pk, self.cardiologo.pk,
            MANANA_10.replace(hour=15),
        )

        response = self._paso_3()

        jueves = response.context['semana']['dias'][3]
        self.assertEqual(len(jueves['horarios']), 11)
        self.assertNotIn(
            MANANA_10.replace(hour=15),
            [h['fecha_hora'] for h in jueves['horarios']],
        )

    def test_parametros_invalidos_en_la_url_dan_404(self):
        casos = {
            'mascota ajena': {'mascota': self.michi.pk},
            'mascota ajena con especialidad': {
                'mascota': self.michi.pk, 'especialidad': 'CARDIOLOGIA',
            },
            'guardia': {
                'mascota': self.firulais.pk, 'especialidad': 'GUARDIA',
            },
            'vacunacion': {
                'mascota': self.firulais.pk, 'especialidad': 'VACUNACION',
            },
            'especialidad inventada': {
                'mascota': self.firulais.pk, 'especialidad': 'MAGIA',
            },
            'veterinario de otra especialidad': {
                'mascota': self.firulais.pk, 'especialidad': 'CARDIOLOGIA',
                'veterinario': self.clinico.pk,
            },
        }
        for caso, parametros in casos.items():
            with self.subTest(caso=caso):
                response = self.client.get(URL_NUEVO, parametros)
                self.assertEqual(response.status_code, 404)

    def test_el_link_de_un_horario_lleva_a_la_confirmacion(self):
        paso_3 = self._paso_3()
        link = html.unescape(re.search(
            r'href="([^"]*confirmar/[^"]*)"', paso_3.content.decode(),
        ).group(1))

        response = self.client.get(link)

        self.assertEqual(response.status_code, 200)
        horario = response.context['horario']
        self.assertEqual(horario['veterinario'], self.cardiologo)
        self.assertEqual(horario['fecha_hora'], AHORA.replace(hour=13))
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Cardiología')
        self.assertContains(response, 'Dr. Federico Acosta')
        self.assertContains(response, 'Miércoles 14 de octubre')
        self.assertContains(response, '13:00 hs')
        self.assertContains(response, '$28.000')
        self.assertContains(response, 'name="motivo"')
        self.assertEqual(Turno.objects.count(), 0)

    def test_reservar_redirige_a_mis_consultas_con_el_mensaje(self):
        response = self.client.post(
            URL_CONFIRMAR,
            self._datos_confirmacion(motivo='  Control anual  '),
            follow=True,
        )

        self.assertRedirects(response, reverse('atencion:consultas'))
        self.assertContains(
            response,
            '¡Turno reservado para Firulais el jueves 15 de octubre a las '
            '10:00!',
        )
        turno = Turno.objects.get()
        self.assertEqual(turno.mascota, self.firulais)
        self.assertEqual(turno.veterinario, self.clinico)
        self.assertEqual(turno.fecha_hora, MANANA_10)
        self.assertEqual(turno.tipo, 'Consulta Regular')
        self.assertEqual(turno.motivo, 'Control anual')
        self.assertEqual(turno.pagos.get().monto_total, 15000)
        self.assertContains(response, 'Dra. Laura Fernández')

    def test_horario_ya_tomado_vuelve_al_paso_3_con_el_error(self):
        reservar_turno(
            self.beto, self.michi.pk, self.clinico.pk, MANANA_10,
        )
        url_paso_3 = (
            f'{URL_NUEVO}?mascota={self.firulais.pk}'
            '&especialidad=CLINICA_GENERAL'
        )

        por_get = self.client.get(
            URL_CONFIRMAR, self._datos_confirmacion(), follow=True,
        )
        por_post = self.client.post(
            URL_CONFIRMAR, self._datos_confirmacion(), follow=True,
        )

        self.assertRedirects(por_get, url_paso_3)
        self.assertContains(por_get, 'ya no está disponible')
        self.assertRedirects(por_post, url_paso_3)
        self.assertContains(por_post, 'acaba de ser reservado')
        self.assertEqual(Turno.objects.count(), 1)

    def test_confirmar_con_datos_invalidos_da_404_y_no_reserva(self):
        casos = {
            'mascota ajena': {'mascota': self.michi.pk},
            'guardia': {
                'especialidad': 'GUARDIA', 'veterinario': self.guardia.pk,
            },
            'veterinario de guardia': {'veterinario': self.guardia.pk},
        }
        for caso, cambios in casos.items():
            with self.subTest(caso=caso):
                datos = self._datos_confirmacion(**cambios)
                self.assertEqual(
                    self.client.get(URL_CONFIRMAR, datos).status_code, 404,
                )
                self.assertEqual(
                    self.client.post(URL_CONFIRMAR, datos).status_code, 404,
                )
        self.assertEqual(Turno.objects.count(), 0)

    def test_los_accesos_a_sacar_turno_llevan_al_flujo_nuevo(self):
        mascotas = self.client.get(reverse('clinica:mascotas'))
        consultas = self.client.get(reverse('atencion:consultas'))
        panel = self.client.get(reverse('clinica:panel'))

        self.assertContains(
            mascotas, f'href="{URL_NUEVO}?mascota={self.firulais.pk}"',
        )
        for response in (consultas, panel):
            self.assertContains(response, f'href="{URL_NUEVO}"')


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
