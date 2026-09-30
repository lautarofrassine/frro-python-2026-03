from django.test import SimpleTestCase
from django.urls import reverse


class InicioViewTests(SimpleTestCase):

    def test_get_devuelve_200_con_nombre_y_link_al_triage(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/inicio.html')
        self.assertContains(response, 'ClinicaVet24')
        self.assertContains(response, reverse('atencion:triage'))
