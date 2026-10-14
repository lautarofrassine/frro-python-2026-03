import re

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

        self.assertContains(response, 'id="boton-urgencia"')
        self.assertContains(response, 'bi-exclamation-triangle-fill')
        self.assertContains(response, 'icono-urgencia')
        self.assertNotContains(response, 'Contactanos')

    def test_el_boton_urgencia_usa_las_mismas_clases_que_sacar_turno(self):
        contenido = self.client.get(reverse('core:inicio')).content.decode()

        sacar_turno = re.search(
            r'<a href="/atencion/turnos/nuevo/"\s+class="([^"]*)"', contenido,
        ).group(1)
        urgencia = re.search(
            r'<a href="[^"]*"\s+class="([^"]*)" id="boton-urgencia"',
            contenido,
        ).group(1)

        self.assertEqual(urgencia, sacar_turno)
        self.assertEqual(urgencia, 'btn btn-brand btn-lg')

    def test_la_tarjeta_urgencias_y_el_boton_van_a_la_misma_url(self):
        contenido = self.client.get(reverse('core:inicio')).content.decode()

        boton = re.search(
            r'<a href="([^"]*)"[^>]*id="boton-urgencia"', contenido,
        ).group(1)
        tarjeta = re.search(
            r'<a href="([^"]*)"\s+id="tarjeta-urgencias"\s+class="([^"]*)"',
            contenido,
        )

        self.assertEqual(tarjeta.group(1), boton)
        self.assertEqual(boton, reverse('atencion:urgencia'))
        # stretched-link: toda la tarjeta es clickeable.
        self.assertIn('stretched-link', tarjeta.group(2))
        self.assertIn('Urgencias 24 hs', contenido)

    def test_el_css_se_carga_con_version_para_evitar_la_cache(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertRegex(
            response.content.decode(),
            r'href="/static/css/estilos\.css\?v=\d+" rel="stylesheet"',
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
