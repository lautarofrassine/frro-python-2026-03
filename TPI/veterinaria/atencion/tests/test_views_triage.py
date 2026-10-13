from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from atencion.forms import TriageForm
from atencion.ml.preparar_datos import FEATURES
from clinica.services.mascotas import registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota


def _datos_post_validos(mascota_id, **overrides):
    datos = {
        'mascota': str(mascota_id),
        'especie': 'perro',
        'edad': '4',
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


class TriageViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.mascota = registrar_mascota(cls.ana, **datos_mascota())
        beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.mascota_ajena = registrar_mascota(
            beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        self.client.force_login(self.ana.usuario)

    def test_get_muestra_formulario_con_solo_sus_mascotas(self):
        response = self.client.get(reverse('atencion:triage'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertContains(response, '<form')
        self.assertContains(response, 'Firulais')
        self.assertNotContains(response, 'Michi')

    @patch('atencion.views.obtener_turnos_disponibles', return_value=[])
    @patch('atencion.views.clasificar_urgencia')
    def test_post_valido_muestra_resultado(self, mock_clasificar, _turnos):
        mock_clasificar.return_value = {
            'nivel': 'ALTA',
            'nivel_modelo': 'MEDIA',
            'regla_aplicada': 'Dificultad respiratoria: nivel minimo ALTA.',
        }

        response = self.client.post(
            reverse('atencion:triage'), _datos_post_validos(self.mascota.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_resultado.html')
        self.assertContains(response, 'ALTA')
        self.assertContains(response, 'Dificultad respiratoria')
        self.assertEqual(response.context['mascota_id'], self.mascota.pk)
        mock_clasificar.assert_called_once()

    @patch('atencion.views.clasificar_urgencia')
    def test_post_invalido_vuelve_a_mostrar_formulario_con_errores(
        self, mock_clasificar,
    ):
        datos = _datos_post_validos(self.mascota.pk)
        del datos['especie']

        response = self.client.post(reverse('atencion:triage'), datos)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertTrue(response.context['form'].errors)
        mock_clasificar.assert_not_called()

    @patch('atencion.views.clasificar_urgencia')
    def test_post_con_mascota_de_otro_dueno_es_invalido(
        self, mock_clasificar,
    ):
        response = self.client.post(
            reverse('atencion:triage'),
            _datos_post_validos(self.mascota_ajena.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('mascota', response.context['form'].errors)
        mock_clasificar.assert_not_called()


class TriageFormFeaturesTests(SimpleTestCase):
    """Guarda contra el desfasaje entre TriageForm y FEATURES: si se
    agrega/renombra una feature en preparar_datos.py sin actualizar el
    form, esto falla en vez de romper recien en produccion."""

    def test_form_cubre_exactamente_las_features_del_modelo(self):
        # 'especie' mapea a 'es_perro' en a_datos_triage, y 'mascota'
        # identifica al paciente pero no es una feature del modelo.
        campos_form = set(TriageForm.base_fields.keys())
        features_esperadas = (
            (campos_form - {'especie', 'mascota'}) | {'es_perro'}
        )

        self.assertEqual(features_esperadas, set(FEATURES))
