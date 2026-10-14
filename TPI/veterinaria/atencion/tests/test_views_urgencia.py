from datetime import date, time
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from administracion.models import Pago
from atencion.forms import TriageForm
from atencion.ml.preparar_datos import FEATURES
from atencion.models import Turno, Veterinario
from atencion.tests.test_turnos import AHORA, TurnosBase, crear_veterinario
from clinica.models import Mascota
from clinica.services.mascotas import MascotaError, registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

URL = reverse('atencion:urgencia')


def _resultado(nivel, regla=None):
    return {'nivel': nivel, 'nivel_modelo': nivel, 'regla_aplicada': regla}


class UrgenciaSinSesionTests(SimpleTestCase):

    def test_muestra_como_llegar_a_la_guardia_y_los_botones_de_ingreso(self):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vení directo a la guardia')
        self.assertContains(response, 'Av. Pellegrini 1250, Rosario, Santa Fe')
        self.assertContains(response, '(0341) 555-0000')
        self.assertContains(
            response,
            'href="https://www.google.com/maps/search/?api=1&amp;query='
            'Av.+Pellegrini+1250%2C+Rosario%2C+Santa+Fe"',
        )
        self.assertContains(response, 'Cómo llegar')
        self.assertContains(response, 'href="tel:+543415550000"')
        self.assertContains(
            response, f'href="{reverse("clinica:ingresar")}?next={URL}"',
        )
        self.assertContains(
            response, f'href="{reverse("clinica:registro")}?next={URL}"',
        )
        self.assertNotContains(response, '<form')

    def test_post_sin_sesion_manda_a_ingresar(self):
        response = self.client.post(URL, {})

        self.assertRedirects(
            response, f"{reverse('clinica:ingresar')}?next={URL}",
            fetch_redirect_response=False,
        )

    def test_la_direccion_vieja_del_triage_redirige_a_urgencia(self):
        response = self.client.get('/atencion/triage/')

        self.assertRedirects(response, URL, fetch_redirect_response=False)


class UrgenciaSinMascotasTests(TestCase):

    def test_dueno_sin_mascotas_va_a_registrar_una(self):
        self.client.force_login(crear_dueno().usuario)

        response = self.client.get(URL)

        self.assertRedirects(response, reverse('clinica:mascota_nueva'))


class UrgenciaBase(TurnosBase):
    """Firulais (perro de Ana) nacio el 10/05/2020: el 14/10/2026 tiene
    6 años y 5 meses. Son las 12:00 del miercoles 14/10/2026."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gata = registrar_mascota(cls.ana, **datos_mascota(
            nombre='Luna', especie='GATO',
            fecha_nacimiento=date(2026, 4, 14),
        ))
        cls.guardia = crear_veterinario(
            'Dra. Luciana Paz', 'MP-5025', 'GUARDIA',
            time(8, 0), time(16, 0), dias=range(7),
        )

    def setUp(self):
        super().setUp()
        parche = patch(
            'clinica.services.mascotas._hoy', return_value=AHORA.date(),
        )
        parche.start()
        self.addCleanup(parche.stop)
        self.client.force_login(self.ana.usuario)

    def evaluar(self, nivel, mascota=None, regla=None, **datos):
        datos_post = {
            'mascota': (mascota or self.firulais).pk,
            'dias_evolucion': '1',
            'temperatura': '',
            'vomitos': 'on',
        }
        datos_post.update(datos)
        with patch('atencion.services.triage.clasificar_urgencia',
                   return_value=_resultado(nivel, regla)) as clasificar:
            response = self.client.post(URL, datos_post)
        self.clasificar = clasificar
        return response


class UrgenciaFormularioTests(UrgenciaBase):

    def test_get_muestra_la_franja_y_el_formulario_con_sus_mascotas(self):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/urgencia.html')
        self.assertContains(response, 'vení directo a la guardia')
        self.assertContains(response, 'Firulais (Perro, 6 años y 5 meses)')
        self.assertContains(response, 'Luna (Gato, 6 meses)')
        self.assertNotContains(response, 'Michi')
        self.assertNotIn('edad', response.context['form'].fields)
        self.assertNotIn('especie', response.context['form'].fields)

    def test_le_pasa_al_modelo_la_edad_y_especie_de_la_mascota(self):
        self.evaluar('BAJA')
        datos_perro = self.clasificar.call_args.args[0]
        self.evaluar('BAJA', mascota=self.gata)
        datos_gata = self.clasificar.call_args.args[0]

        self.assertEqual(datos_perro['edad'], 6.42)
        self.assertEqual(datos_perro['es_perro'], 'perro')
        self.assertEqual(datos_gata['edad'], 0.5)
        self.assertEqual(datos_gata['es_perro'], 'gato')
        self.assertEqual(set(datos_perro), set(FEATURES))
        self.assertIs(datos_perro['vomitos'], True)

    def test_post_con_el_modelo_real_no_rompe(self):
        response = self.client.post(URL, {
            'mascota': self.gata.pk, 'dias_evolucion': '2',
            'temperatura': '', 'vomitos': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.context['resultado']['nivel'],
            {'BAJA', 'MEDIA', 'ALTA', 'CRITICA'},
        )

    def test_post_invalido_vuelve_a_mostrar_el_formulario(self):
        response = self.evaluar('BAJA', dias_evolucion='')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/urgencia.html')
        self.assertTrue(response.context['form'].errors)
        self.clasificar.assert_not_called()

    def test_post_con_mascota_de_otro_dueno_es_invalido(self):
        response = self.evaluar('CRITICA', mascota=self.michi)

        self.assertEqual(response.status_code, 200)
        self.assertIn('mascota', response.context['form'].errors)
        self.clasificar.assert_not_called()
        self.assertEqual(Turno.objects.count(), 0)

    def test_mascota_sin_fecha_de_nacimiento_muestra_error_con_link(self):
        # La base no admite fecha nula; se simula el dato viejo haciendo
        # fallar el calculo de edad como lo haria el service.
        error = MascotaError(
            'Firulais no tiene fecha de nacimiento cargada. Completala '
            'en "Mis mascotas" para poder calcular su edad.',
            'fecha_nacimiento',
        )
        with patch('atencion.services.triage.edad_en_anios',
                   side_effect=error):
            response = self.evaluar('BAJA')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/urgencia.html')
        self.assertContains(response, 'no tiene fecha de nacimiento cargada')
        self.assertContains(
            response,
            reverse('clinica:mascota_editar', args=[self.firulais.pk]),
        )


class UrgenciaCriticaTests(UrgenciaBase):

    def test_reserva_sola_el_primer_turno_de_guardia(self):
        response = self.evaluar('CRITICA')

        turno = Turno.objects.get()
        self.assertEqual(turno.mascota, self.firulais)
        self.assertEqual(turno.veterinario, self.guardia)
        self.assertEqual(turno.fecha_hora, AHORA.replace(minute=30))
        self.assertEqual(turno.tipo, 'Guardia')
        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'CRITICA')
        pago = Pago.objects.get()
        self.assertEqual(pago.turno, turno)
        self.assertEqual(pago.monto_total, 30000)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

        self.assertTemplateUsed(response, 'atencion/urgencia_resultado.html')
        self.assertContains(response, '¡URGENCIA CRÍTICA!')
        self.assertContains(
            response, 'Llevá a Firulais a la guardia AHORA.',
        )
        self.assertContains(response, 'alerta-critica')
        self.assertContains(response, 'bi-exclamation-triangle-fill')
        self.assertContains(response, 'Av. Pellegrini 1250, Rosario, Santa Fe')
        self.assertContains(response, 'google.com/maps')
        self.assertContains(response, 'Llamar ahora')
        self.assertContains(response, 'href="tel:+543415550000"')
        self.assertContains(response, 'Turno de guardia reservado:')
        self.assertContains(response, 'hoy 12:30')
        self.assertContains(response, 'Dra. Luciana Paz')

    def test_enviar_dos_veces_no_crea_dos_turnos(self):
        self.evaluar('CRITICA')

        response = self.evaluar('CRITICA')

        self.assertEqual(Turno.objects.count(), 1)
        self.assertEqual(Pago.objects.count(), 1)
        self.assertContains(response, 'hoy 12:30')

    def test_otra_mascota_si_recibe_su_propio_turno(self):
        self.evaluar('CRITICA')

        self.evaluar('CRITICA', mascota=self.gata)

        self.assertEqual(Turno.objects.count(), 2)
        self.assertEqual(
            Turno.objects.get(mascota=self.gata).fecha_hora,
            AHORA.replace(hour=13, minute=0),
        )

    def test_no_usa_veterinarios_que_no_son_de_guardia(self):
        # A las 12:30 tambien esta libre la clinica general.
        self.evaluar('CRITICA')

        self.assertEqual(
            Turno.objects.get().veterinario.especialidad,
            Veterinario.Especialidad.GUARDIA,
        )

    def test_sin_turnos_de_guardia_muestra_la_alerta_sin_error(self):
        self.guardia.estado = 'INACTIVO'
        self.guardia.save()

        response = self.evaluar('CRITICA')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡URGENCIA CRÍTICA!')
        self.assertContains(response, 'Av. Pellegrini 1250, Rosario, Santa Fe')
        self.assertContains(response, 'Vení igual, te atendemos.')
        self.assertNotContains(response, 'Turno de guardia reservado')
        self.assertEqual(Turno.objects.count(), 0)

    def test_el_nombre_del_profesional_no_repite_el_titulo(self):
        resultado = self.evaluar('CRITICA')
        consultas = self.client.get(reverse('atencion:consultas'))

        for response in (resultado, consultas):
            self.assertContains(response, 'Dra. Luciana Paz')
            for repetido in ('Dr/a.', 'Dra. Dra.', 'Dr. Dra.', 'Dr. Dr.'):
                self.assertNotContains(response, repetido)


class UrgenciaAltaTests(UrgenciaBase):

    def test_propone_un_turno_de_guardia_sin_reservarlo(self):
        response = self.evaluar(
            'ALTA', regla='Dificultad respiratoria: nivel minimo ALTA.',
        )

        self.assertEqual(Turno.objects.count(), 0)
        self.assertContains(response, 'Urgencia alta')
        self.assertContains(response, 'Acercate con Firulais a la guardia')
        self.assertContains(response, 'lo antes posible.')
        self.assertContains(response, 'bg-alta')
        self.assertContains(response, 'Av. Pellegrini 1250, Rosario, Santa Fe')
        self.assertContains(response, 'Cómo llegar')
        self.assertContains(response, 'Confirmar turno de guardia')
        self.assertContains(response, 'hoy 12:30')
        self.assertContains(response, 'Dificultad respiratoria')
        propuesto = response.context['resultado']['plan']['turno_propuesto']
        self.assertEqual(propuesto['veterinario_id'], self.guardia.pk)
        self.assertNotContains(response, '¡URGENCIA CRÍTICA!')

    def test_confirmar_reserva_el_turno_propuesto(self):
        propuesto = self.evaluar('ALTA').context['resultado']['plan'][
            'turno_propuesto'
        ]
        datos = {
            'mascota': self.firulais.pk,
            'veterinario': propuesto['veterinario_id'],
            'fecha_hora': propuesto['fecha_hora'].isoformat(),
        }

        response = self.client.post(
            reverse('atencion:urgencia_confirmar'), datos, follow=True,
        )
        self.client.post(reverse('atencion:urgencia_confirmar'), datos)

        turno = Turno.objects.get()
        self.assertEqual(turno.tipo, 'Guardia')
        self.assertEqual(turno.nivel_urgencia.nivel_urgencia, 'ALTA')
        self.assertEqual(turno.veterinario, self.guardia)
        self.assertEqual(turno.fecha_hora, AHORA.replace(minute=30))
        self.assertEqual(turno.pagos.count(), 1)
        self.assertRedirects(response, reverse('atencion:consultas'))
        self.assertContains(
            response, 'Turno de guardia reservado para Firulais',
        )

    def test_confirmar_no_acepta_veterinarios_que_no_son_de_guardia(self):
        self.client.post(reverse('atencion:urgencia_confirmar'), {
            'mascota': self.firulais.pk,
            'veterinario': self.clinico.pk,
            'fecha_hora': AHORA.replace(minute=30).isoformat(),
        })

        self.assertEqual(Turno.objects.get().veterinario, self.guardia)

    def test_confirmar_con_mascota_ajena_o_sin_guardia_avisa(self):
        ajena = self.client.post(
            reverse('atencion:urgencia_confirmar'),
            {'mascota': self.michi.pk}, follow=True,
        )
        self.guardia.estado = 'INACTIVO'
        self.guardia.save()
        sin_guardia = self.client.post(
            reverse('atencion:urgencia_confirmar'),
            {'mascota': self.firulais.pk}, follow=True,
        )

        self.assertContains(ajena, 'no está entre tus mascotas')
        self.assertContains(sin_guardia, 'No quedan turnos de guardia')
        self.assertEqual(Turno.objects.count(), 0)

    def test_confirmar_por_get_no_esta_permitido(self):
        response = self.client.get(reverse('atencion:urgencia_confirmar'))

        self.assertEqual(response.status_code, 405)


class UrgenciaLeveTests(UrgenciaBase):

    def test_media_y_baja_no_reservan_y_ofrecen_sacar_turno(self):
        for nivel in ('MEDIA', 'BAJA'):
            with self.subTest(nivel=nivel):
                response = self.evaluar(nivel)

                self.assertEqual(Turno.objects.count(), 0)
                self.assertContains(response, 'No parece una emergencia')
                self.assertContains(
                    response, 'Te recomendamos sacar un turno de consulta.',
                )
                self.assertContains(
                    response,
                    f'{reverse("atencion:turno_nuevo")}'
                    f'?mascota={self.firulais.pk}',
                )
                self.assertContains(
                    response, 'edad usada: 6 años y 5 meses',
                )
                self.assertNotContains(response, 'Confirmar turno de guardia')
                self.assertNotContains(response, 'URGENCIA CRÍTICA')


class TriageFormTests(SimpleTestCase):

    def test_form_mas_la_mascota_cubren_las_features_del_modelo(self):
        """Guarda contra el desfasaje entre TriageForm y FEATURES: 'edad'
        y 'es_perro' salen de la mascota (evaluar_mascota) y el resto de
        las features tienen que ser campos del form."""
        campos_form = set(TriageForm.base_fields.keys())
        features_cubiertas = (campos_form - {'mascota'}) | {'edad', 'es_perro'}

        self.assertEqual(features_cubiertas, set(FEATURES))

    def test_opcion_de_mascota_sin_fecha_de_nacimiento_no_rompe(self):
        sin_fecha = Mascota(
            pk=1, nombre='Viejo', especie='PERRO', fecha_nacimiento=None,
        )

        form = TriageForm(mascotas=[sin_fecha])

        self.assertIn(
            (1, 'Viejo (Perro, sin fecha de nacimiento)'),
            form.fields['mascota'].choices,
        )
