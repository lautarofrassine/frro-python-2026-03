from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from atencion.forms import TriageForm
from atencion.ml.preparar_datos import FEATURES


def _datos_post_validos(**overrides):
    datos = {
        'especie': 'perro',
        'edad': '4',
        'dias_evolucion': '2',
        'temperatura': '',
        'vomitos': 'on',
    }
    datos.update(overrides)
    return datos


class TriageViewTests(SimpleTestCase):

    def test_get_muestra_formulario(self):
        response = self.client.get(reverse('atencion:triage'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertContains(response, '<form')

    @patch('atencion.views.clasificar_urgencia')
    def test_post_valido_muestra_resultado(self, mock_clasificar):
        mock_clasificar.return_value = {
            'nivel': 'ALTA',
            'nivel_modelo': 'MEDIA',
            'regla_aplicada': 'Dificultad respiratoria: nivel minimo ALTA.',
        }

        response = self.client.post(
            reverse('atencion:triage'), _datos_post_validos(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_resultado.html')
        self.assertContains(response, 'ALTA')
        self.assertContains(response, 'Dificultad respiratoria')
        mock_clasificar.assert_called_once()

    @patch('atencion.views.clasificar_urgencia')
    def test_post_invalido_vuelve_a_mostrar_formulario_con_errores(
        self, mock_clasificar,
    ):
        datos = _datos_post_validos()
        del datos['especie']

        response = self.client.post(reverse('atencion:triage'), datos)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'atencion/triage_form.html')
        self.assertTrue(response.context['form'].errors)
        mock_clasificar.assert_not_called()


class TriageFormFeaturesTests(SimpleTestCase):
    """Guarda contra el desfasaje entre TriageForm y FEATURES: si se
    agrega/renombra una feature en preparar_datos.py sin actualizar el
    form, esto falla en vez de romper recien en produccion."""

    def test_form_cubre_exactamente_las_features_del_modelo(self):
        # El unico campo del form que no se llama igual que su feature
        # es 'especie' (mapea a 'es_perro' en a_datos_triage).
        campos_form = set(TriageForm.base_fields.keys())
        features_esperadas = (campos_form - {'especie'}) | {'es_perro'}

        self.assertEqual(features_esperadas, set(FEATURES))
