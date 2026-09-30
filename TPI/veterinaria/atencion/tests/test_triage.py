from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from atencion.ml.preparar_datos import (
    FEATURES,
    _convertir_dias_evolucion,
    _convertir_temperatura,
)
from atencion.services.triage import clasificar_urgencia


def _datos_base(**overrides):
    datos = {feature: False for feature in FEATURES}
    datos.update({
        'es_perro': 'perro',
        'edad': 3,
        'temperatura': 38.5,
        'dias_evolucion': 2,
    })
    datos.update(overrides)
    return datos


def _mock_modelo(nivel_predicho):
    modelo = Mock()
    modelo.predict = Mock(return_value=[nivel_predicho])
    return modelo


class ReglasDeSeguridadTests(SimpleTestCase):

    @patch('atencion.services.triage._cargar_modelo')
    def test_dificultad_respiratoria_sube_a_alta_minimo(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('BAJA')
        datos = _datos_base(dificultad_respiratoria=True)

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'ALTA')
        self.assertEqual(resultado['nivel_modelo'], 'BAJA')
        self.assertIsNotNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_temperatura_alta_sube_a_alta_minimo(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('BAJA')
        datos = _datos_base(temperatura=40.2)

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'ALTA')
        self.assertIsNotNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_triada_shock_sube_a_alta_minimo(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('MEDIA')
        datos = _datos_base(vomitos=True, diarrea=True, deshidratacion=True)

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'ALTA')
        self.assertIsNotNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_respiratoria_y_temperatura_dan_critica(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('BAJA')
        datos = _datos_base(dificultad_respiratoria=True, temperatura=40.5)

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'CRITICA')
        self.assertIsNotNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_ninguna_regla_baja_un_nivel_critico(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('CRITICA')
        datos = _datos_base()

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'CRITICA')
        self.assertEqual(resultado['nivel_modelo'], 'CRITICA')
        self.assertIsNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_regla_activa_no_baja_nivel_ya_critico(self, mock_cargar):
        mock_cargar.return_value = _mock_modelo('CRITICA')
        datos = _datos_base(dificultad_respiratoria=True)

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'CRITICA')
        self.assertIsNone(resultado['regla_aplicada'])

    @patch('atencion.services.triage._cargar_modelo')
    def test_sin_sintomas_graves_devuelve_nivel_del_modelo(self, mock_c):
        mock_c.return_value = _mock_modelo('MEDIA')
        datos = _datos_base()

        resultado = clasificar_urgencia(datos)

        self.assertEqual(resultado['nivel'], 'MEDIA')
        self.assertEqual(resultado['nivel_modelo'], 'MEDIA')
        self.assertIsNone(resultado['regla_aplicada'])


class ValidacionDatosTests(SimpleTestCase):

    def test_datos_incompletos_lanza_value_error(self):
        datos = _datos_base()
        del datos['edad']

        with self.assertRaises(ValueError):
            clasificar_urgencia(datos)


class PrepararDatosTests(SimpleTestCase):

    def test_duracion_en_semanas_se_convierte_a_dias(self):
        self.assertEqual(_convertir_dias_evolucion('1 week'), 7)

    def test_duracion_en_dias_se_mantiene(self):
        self.assertEqual(_convertir_dias_evolucion('3 days'), 3)

    def test_temperatura_extrae_valor_float(self):
        self.assertEqual(_convertir_temperatura('39.5°C'), 39.5)
