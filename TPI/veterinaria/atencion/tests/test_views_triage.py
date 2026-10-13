from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from atencion.forms import TriageForm
from atencion.ml.preparar_datos import FEATURES
from clinica.models import Mascota
from clinica.services.mascotas import MascotaError, registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

HOY = date(2026, 10, 14)
RESULTADO_MODELO = {
    'nivel': 'ALTA',
    'nivel_modelo': 'MEDIA',
    'regla_aplicada': 'Dificultad respiratoria: nivel minimo ALTA.',
}


def _datos_post_validos(mascota_id, **overrides):
    datos = {
        'mascota': str(mascota_id),
        'dias_evolucion': '2',
        'temperatura': '',
        'vomitos': 'on',
    }
    datos.update(overrides)
    return datos


class TriageSinSesionTests(SimpleTestCase):

    def test_sin_sesion_redirige_al_login_con_next(self):
        url_triage = reverse('atencion:triage')

        response = self.client.get(url_triage)

        self.assertRedirects(
            response,
            f"{reverse('clinica:ingresar')}?next={url_triage}",
            fetch_redirect_response=False,
        )


class TriageSinMascotasTests(TestCase):

    def test_dueno_sin_mascotas_va_a_registrar_una(self):
        self.client.force_login(crear_dueno().usuario)

        response = self.client.get(reverse('atencion:triage'))

        self.assertRedirects(response, reverse('clinica:mascota_nueva'))


@patch('atencion.views.obtener_turnos_disponibles', return_value=[])
@patch('clinica.services.mascotas._hoy', return_value=HOY)
class TriageViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        # Nacido el 10/05/2020: el 14/10/2026 tiene 6 años y 5 meses.
        cls.perro = registrar_mascota(cls.ana, **datos_mascota())
        cls.gata = registrar_mascota(cls.ana, **datos_mascota(
            nombre='Luna', especie='GATO',
            fecha_nacimiento=date(2026, 4, 14),
        ))
        beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.mascota_ajena = registrar_mascota(
            beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        self.client.force_login(self.ana.usuario)

    def test_get_muestra_sus_mascotas_con_especie_y_edad(self, *_):
        response = self.client.get(reverse('atencion:triage'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertContains(response, 'Firulais (Perro, 6 años y 5 meses)')
        self.assertContains(response, 'Luna (Gato, 6 meses)')
        self.assertNotContains(response, 'Michi')

    def test_el_formulario_ya_no_pide_edad_ni_especie(self, *_):
        response = self.client.get(reverse('atencion:triage'))

        self.assertNotIn('edad', response.context['form'].fields)
        self.assertNotIn('especie', response.context['form'].fields)
        self.assertNotContains(response, 'name="edad"')
        self.assertNotContains(response, 'name="especie"')

    @patch('atencion.services.triage.clasificar_urgencia')
    def test_le_pasa_al_modelo_la_edad_y_especie_de_la_mascota(
        self, mock_clasificar, *_,
    ):
        mock_clasificar.return_value = dict(RESULTADO_MODELO)

        self.client.post(
            reverse('atencion:triage'), _datos_post_validos(self.perro.pk),
        )
        datos_perro = mock_clasificar.call_args.args[0]
        self.client.post(
            reverse('atencion:triage'), _datos_post_validos(self.gata.pk),
        )
        datos_gata = mock_clasificar.call_args.args[0]

        self.assertEqual(datos_perro['edad'], 6.42)
        self.assertEqual(datos_perro['es_perro'], 'perro')
        self.assertEqual(datos_gata['edad'], 0.5)
        self.assertEqual(datos_gata['es_perro'], 'gato')
        self.assertEqual(set(datos_perro), set(FEATURES))
        self.assertIs(datos_perro['vomitos'], True)

    @patch('atencion.services.triage.clasificar_urgencia')
    def test_post_valido_muestra_resultado_con_la_edad_usada(
        self, mock_clasificar, *_,
    ):
        mock_clasificar.return_value = dict(RESULTADO_MODELO)

        response = self.client.post(
            reverse('atencion:triage'), _datos_post_validos(self.perro.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_resultado.html')
        self.assertContains(response, 'ALTA')
        self.assertContains(response, 'Dificultad respiratoria')
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'edad usada: 6 años y 5 meses')
        self.assertEqual(response.context['mascota_id'], self.perro.pk)

    def test_post_valido_con_el_modelo_real_no_rompe(self, *_):
        response = self.client.post(
            reverse('atencion:triage'), _datos_post_validos(self.gata.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.context['resultado']['nivel'],
            {'BAJA', 'MEDIA', 'ALTA', 'CRITICA'},
        )

    @patch('atencion.services.triage.clasificar_urgencia')
    def test_post_invalido_vuelve_a_mostrar_formulario_con_errores(
        self, mock_clasificar, *_,
    ):
        datos = _datos_post_validos(self.perro.pk)
        del datos['dias_evolucion']

        response = self.client.post(reverse('atencion:triage'), datos)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertTrue(response.context['form'].errors)
        mock_clasificar.assert_not_called()

    @patch('atencion.services.triage.clasificar_urgencia')
    def test_post_con_mascota_de_otro_dueno_es_invalido(
        self, mock_clasificar, *_,
    ):
        response = self.client.post(
            reverse('atencion:triage'),
            _datos_post_validos(self.mascota_ajena.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('mascota', response.context['form'].errors)
        mock_clasificar.assert_not_called()

    @patch('atencion.services.triage.clasificar_urgencia')
    def test_mascota_sin_fecha_de_nacimiento_muestra_error_con_link(
        self, mock_clasificar, *_,
    ):
        # La base no admite fecha nula; se simula el dato viejo haciendo
        # fallar el calculo de edad como lo haria el service.
        error = MascotaError(
            'Firulais no tiene fecha de nacimiento cargada. Completala '
            'en "Mis mascotas" para poder calcular su edad.',
            'fecha_nacimiento',
        )
        with patch('atencion.services.triage.edad_en_anios',
                   side_effect=error):
            response = self.client.post(
                reverse('atencion:triage'),
                _datos_post_validos(self.perro.pk),
            )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertContains(response, 'no tiene fecha de nacimiento cargada')
        self.assertContains(
            response, reverse('clinica:mascota_editar', args=[self.perro.pk]),
        )
        mock_clasificar.assert_not_called()


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
