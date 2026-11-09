from datetime import time
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from administracion.tests.test_obras_sociales import crear_obras_sociales
from atencion.tests.test_turnos import crear_veterinario
from clinica.tests.test_mascotas import crear_dueno

URL_PERFIL = reverse('clinica:perfil')
URL_OBRAS_VET = reverse('veterinario:obras_sociales')


class ObrasSocialesVistasBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.obras, cls.inactiva = crear_obras_sociales()
        cls.vetsalud = cls.obras['VetSalud Plus']
        cls.huellitas = cls.obras['Huellitas Total']
        cls.dueno = crear_dueno()
        cls.veterinario = crear_veterinario(
            'Dra. Laura Fernández', 'MP-5001', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )
        cls.usuario_vet = get_user_model().objects.create_user(
            username='laura.fernandez@clinicavet24.com',
        )
        cls.veterinario.usuario = cls.usuario_vet
        cls.veterinario.save()

    def como_dueno(self):
        self.client.force_login(self.dueno.usuario)

    def como_veterinario(self):
        self.client.force_login(self.usuario_vet)


class PermisosTests(ObrasSocialesVistasBase):

    def test_dueno_no_entra_a_obras_sociales_del_veterinario(self):
        self.como_dueno()

        self.assertEqual(self.client.get(URL_OBRAS_VET).status_code, 403)
        self.assertEqual(self.client.post(URL_OBRAS_VET).status_code, 403)

    def test_veterinario_no_entra_a_mi_perfil(self):
        self.como_veterinario()

        self.assertEqual(self.client.get(URL_PERFIL).status_code, 403)

    def test_sin_sesion_redirige_a_ingresar(self):
        ingresar = reverse('clinica:ingresar')
        for url in (URL_PERFIL, URL_OBRAS_VET):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, f'{ingresar}?next={quote(url)}',
                    fetch_redirect_response=False,
                )


class PerfilTests(ObrasSocialesVistasBase):

    def _datos(self, **cambios):
        datos = {
            'nombre': 'Ana María', 'apellido': 'Gómez',
            'telefono': '341 555-1111',
            'obra_social': str(self.vetsalud.pk), 'numero_afiliado': 'A-77',
        }
        datos.update(cambios)
        return datos

    def test_muestra_el_formulario_con_las_obras_activas(self):
        self.como_dueno()

        response = self.client.get(URL_PERFIL)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'clinica/perfil.html')
        self.assertIn('Sin obra social', contenido)
        self.assertIn('VetSalud Plus', contenido)
        self.assertIn('data-porcentaje="70"', contenido)
        self.assertNotIn('Vieja Cobertura', contenido)
        self.assertIn(self.dueno.email, contenido)
        self.assertIn(self.dueno.dni, contenido)

    def test_guarda_datos_y_obra_social(self):
        self.como_dueno()

        response = self.client.post(URL_PERFIL, self._datos(), follow=True)

        self.assertRedirects(response, URL_PERFIL)
        self.assertContains(response, 'Se guardaron los cambios de tu perfil.')
        self.dueno.refresh_from_db()
        self.assertEqual(self.dueno.nombre, 'Ana María')
        self.assertEqual(self.dueno.telefono, '341 555-1111')
        self.assertEqual(self.dueno.obra_social, self.vetsalud)
        self.assertEqual(self.dueno.numero_afiliado, 'A-77')
        self.assertEqual(self.dueno.usuario.first_name, 'Ana María')

    def test_obra_social_sin_numero_muestra_el_error(self):
        self.como_dueno()

        response = self.client.post(
            URL_PERFIL, self._datos(numero_afiliado=''),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ingresá tu número de afiliado.')
        self.dueno.refresh_from_db()
        self.assertIsNone(self.dueno.obra_social)
        self.assertEqual(self.dueno.nombre, 'Ana')

    def test_obra_social_inactiva_no_se_puede_elegir(self):
        self.como_dueno()

        response = self.client.post(
            URL_PERFIL, self._datos(obra_social=str(self.inactiva.pk)),
        )

        self.assertEqual(response.status_code, 200)
        self.dueno.refresh_from_db()
        self.assertIsNone(self.dueno.obra_social)

    def test_sin_obra_social_limpia_el_numero(self):
        self.como_dueno()
        self.client.post(URL_PERFIL, self._datos())

        self.client.post(URL_PERFIL, self._datos(obra_social=''))

        self.dueno.refresh_from_db()
        self.assertIsNone(self.dueno.obra_social)
        self.assertEqual(self.dueno.numero_afiliado, '')

    def test_el_panel_muestra_la_obra_social(self):
        self.como_dueno()
        panel = reverse('clinica:panel')

        response = self.client.get(panel)
        self.assertContains(response, 'Sin obra social')
        self.assertContains(response, f'href="{URL_PERFIL}"')

        self.client.post(URL_PERFIL, self._datos())
        response = self.client.get(panel)
        self.assertContains(response, 'VetSalud Plus')
        self.assertContains(response, 'A-77')

    def test_el_menu_del_dueno_tiene_mi_perfil(self):
        self.como_dueno()

        response = self.client.get(reverse('clinica:panel'))

        self.assertContains(response, 'Mi perfil')


class ObrasSocialesVeterinarioTests(ObrasSocialesVistasBase):

    def test_muestra_las_activas_y_marca_las_que_atiende(self):
        self.veterinario.obras_sociales.set([self.huellitas])
        self.como_veterinario()

        response = self.client.get(URL_OBRAS_VET)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(contenido.count('name="obras_sociales"'), 4)
        self.assertNotIn('Vieja Cobertura', contenido)
        self.assertRegex(
            contenido,
            rf'value="{self.huellitas.pk}"\s+id="obra-{self.huellitas.pk}"'
            r'\s+checked',
        )
        self.assertNotRegex(
            contenido,
            rf'value="{self.vetsalud.pk}"\s+id="obra-{self.vetsalud.pk}"'
            r'\s+checked',
        )

    def test_guardar_reemplaza_y_confirma(self):
        self.veterinario.obras_sociales.set([self.huellitas])
        self.como_veterinario()

        response = self.client.post(
            URL_OBRAS_VET,
            {'obras_sociales': [self.vetsalud.pk,
                                self.obras['PetCare Básico'].pk]},
            follow=True,
        )

        self.assertRedirects(response, URL_OBRAS_VET)
        self.assertContains(
            response, 'Se guardaron las obras sociales que atendés.',
        )
        self.assertEqual(
            sorted(o.nombre for o in self.veterinario.obras_sociales.all()),
            ['PetCare Básico', 'VetSalud Plus'],
        )

    def test_inactiva_muestra_error_y_no_cambia(self):
        self.veterinario.obras_sociales.set([self.huellitas])
        self.como_veterinario()

        response = self.client.post(
            URL_OBRAS_VET, {'obras_sociales': [self.inactiva.pk]},
            follow=True,
        )

        self.assertContains(response, 'no existe o no está activa')
        self.assertEqual(
            list(self.veterinario.obras_sociales.all()), [self.huellitas],
        )

    def test_la_agenda_muestra_las_obras_que_atiende(self):
        self.como_veterinario()
        agenda = reverse('veterinario:agenda')

        self.assertContains(self.client.get(agenda), 'No atendés obras')

        self.veterinario.obras_sociales.set([self.huellitas, self.vetsalud])
        response = self.client.get(agenda)
        self.assertContains(
            response, 'Atendés: Huellitas Total, VetSalud Plus',
        )
