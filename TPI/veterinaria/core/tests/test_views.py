from django.test import SimpleTestCase
from django.urls import reverse


class InicioViewTests(SimpleTestCase):

    def test_get_devuelve_200_con_nombre_y_link_a_sacar_turno(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/inicio.html')
        self.assertContains(response, 'ClinicaVet24')
        self.assertContains(
            response, f'href="{reverse("atencion:turno_nuevo")}"',
        )

    def test_el_hero_tiene_el_boton_urgencia_y_ya_no_contactanos(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertContains(response, 'btn btn-outline-urgencia btn-lg')
        self.assertContains(response, 'bi-exclamation-triangle-fill')
        self.assertNotContains(response, 'Contactanos')
        # El boton del hero y la tarjeta "Urgencias 24 hs".
        self.assertContains(
            response, f'href="{reverse("atencion:urgencia")}"', count=2,
        )

    def test_los_datos_de_la_clinica_salen_de_la_configuracion_central(self):
        response = self.client.get(reverse('core:inicio'))

        # Footer y seccion de contacto.
        self.assertContains(
            response, 'Av. Pellegrini 1250, Rosario, Santa Fe', count=2,
        )
        self.assertContains(response, '(0341) 555-0000')
        self.assertNotContains(response, 'Siempre Viva')

    def test_tarjeta_consultas_lleva_a_mis_consultas(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertContains(
            response, f'href="{reverse("atencion:consultas")}"',
        )

    def test_tarjeta_mascotas_reemplaza_a_cirugias(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertContains(
            response, 'Registrá a tus mascotas y mantené sus datos al día.',
        )
        self.assertContains(response, reverse('clinica:mascotas'))
        self.assertNotContains(response, 'Cirugías')

    def test_logo_y_favicon_de_la_patita(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertContains(
            response,
            '<link rel="icon" href="/static/img/patita.svg" '
            'type="image/svg+xml">',
        )
        self.assertContains(
            response, '<link rel="icon" href="/static/img/favicon.ico"',
        )
        self.assertContains(
            response,
            '<link rel="apple-touch-icon" href="/static/img/patita-180.png">',
        )
        self.assertContains(
            response, '<img src="/static/img/patita.svg" alt="ClinicaVet24">',
        )
