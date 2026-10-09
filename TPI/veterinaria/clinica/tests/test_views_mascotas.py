from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clinica.models import Mascota
from clinica.services.mascotas import registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota


def datos_post(**overrides):
    datos = {
        'nombre': 'Firulais',
        'especie': 'PERRO',
        'raza': 'Mestizo',
        'fecha_nacimiento': '2020-05-10',
        'peso_kg': '12.5',
    }
    datos.update(overrides)
    return datos


class MascotasSinSesionTests(TestCase):

    def test_todas_las_urls_redirigen_a_ingresar(self):
        dueno = crear_dueno()
        mascota = registrar_mascota(dueno, **datos_mascota())
        urls = [
            reverse('clinica:mascotas'),
            reverse('clinica:mascota_nueva'),
            reverse('clinica:mascota_editar', args=[mascota.pk]),
            reverse('clinica:mascota_baja', args=[mascota.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                for metodo in (self.client.get, self.client.post):
                    response = metodo(url)
                    self.assertRedirects(
                        response,
                        f"{reverse('clinica:ingresar')}?next={url}",
                    )
        mascota.refresh_from_db()
        self.assertTrue(mascota.activo)


class MascotasDeOtroDuenoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.mascota_de_beto = registrar_mascota(
            cls.beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        self.client.force_login(self.ana.usuario)

    def test_no_puede_ver_ni_editar_la_mascota_de_otro(self):
        url = reverse('clinica:mascota_editar', args=[self.mascota_de_beto.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(url, datos_post(nombre='Hackeado'))

        self.assertEqual(response.status_code, 404)
        self.mascota_de_beto.refresh_from_db()
        self.assertEqual(self.mascota_de_beto.nombre, 'Michi')

    def test_no_puede_dar_de_baja_la_mascota_de_otro(self):
        url = reverse('clinica:mascota_baja', args=[self.mascota_de_beto.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.mascota_de_beto.refresh_from_db()
        self.assertTrue(self.mascota_de_beto.activo)

    def test_la_lista_no_muestra_mascotas_de_otro(self):
        response = self.client.get(reverse('clinica:mascotas'))

        self.assertNotContains(response, 'Michi')

    def test_mascota_inexistente_da_404(self):
        url = reverse('clinica:mascota_editar', args=[999999])

        self.assertEqual(self.client.get(url).status_code, 404)


class MascotasAbmTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()

    def setUp(self):
        self.client.force_login(self.ana.usuario)

    def test_lista_vacia_muestra_estado_vacio(self):
        response = self.client.get(reverse('clinica:mascotas'))

        self.assertContains(response, 'Todavía no registraste mascotas')
        self.assertContains(response, 'Agregar mi primera mascota')

    def test_lista_muestra_tarjetas_con_edad_y_peso(self):
        registrar_mascota(self.ana, **datos_mascota())

        response = self.client.get(reverse('clinica:mascotas'))

        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Mestizo')
        # es-ar: coma decimal.
        self.assertContains(response, '12,50 kg')
        self.assertContains(response, 'años')
        self.assertContains(response, 'fa-dog')

    def test_alta_por_post_crea_y_redirige_con_mensaje(self):
        response = self.client.post(
            reverse('clinica:mascota_nueva'), datos_post(), follow=True,
        )

        self.assertRedirects(response, reverse('clinica:mascotas'))
        self.assertContains(response, '¡Firulais fue registrado/a!')
        mascota = Mascota.objects.get(dueno=self.ana)
        self.assertEqual(mascota.fecha_nacimiento, date(2020, 5, 10))
        self.assertEqual(mascota.peso_kg, Decimal('12.50'))

    def test_alta_con_regla_violada_muestra_el_error_del_service(self):
        registrar_mascota(self.ana, **datos_mascota(nombre='Firulais'))

        response = self.client.post(
            reverse('clinica:mascota_nueva'), datos_post(nombre='firulais'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('nombre', response.context['form'].errors)
        self.assertEqual(Mascota.objects.count(), 1)

    def test_alta_con_peso_fuera_de_rango_muestra_error(self):
        response = self.client.post(
            reverse('clinica:mascota_nueva'), datos_post(peso_kg='150'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('peso_kg', response.context['form'].errors)
        self.assertEqual(Mascota.objects.count(), 0)

    def test_editar_get_precarga_el_formulario(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        response = self.client.get(
            reverse('clinica:mascota_editar', args=[mascota.pk]),
        )

        self.assertContains(response, 'value="Firulais"')
        self.assertContains(response, 'value="2020-05-10"')

    def test_edicion_por_post_actualiza_y_redirige_con_mensaje(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        response = self.client.post(
            reverse('clinica:mascota_editar', args=[mascota.pk]),
            datos_post(nombre='Firu', peso_kg='13.2'),
            follow=True,
        )

        self.assertRedirects(response, reverse('clinica:mascotas'))
        self.assertContains(response, 'Los datos de Firu se actualizaron.')
        mascota.refresh_from_db()
        self.assertEqual(mascota.nombre, 'Firu')
        self.assertEqual(mascota.peso_kg, Decimal('13.20'))

    def test_baja_por_get_solo_muestra_la_confirmacion(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        response = self.client.get(
            reverse('clinica:mascota_baja', args=[mascota.pk]),
        )

        self.assertContains(
            response, '¿Seguro que querés dar de baja a Firulais?',
        )
        mascota.refresh_from_db()
        self.assertTrue(mascota.activo)

    def test_baja_por_post_da_de_baja_y_redirige_con_mensaje(self):
        mascota = registrar_mascota(self.ana, **datos_mascota())

        response = self.client.post(
            reverse('clinica:mascota_baja', args=[mascota.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('clinica:mascotas'))
        self.assertContains(response, 'Firulais fue dado/a de baja.')
        mascota.refresh_from_db()
        self.assertFalse(mascota.activo)

    def test_panel_muestra_las_mascotas_y_el_boton_agregar(self):
        registrar_mascota(self.ana, **datos_mascota())

        response = self.client.get(reverse('clinica:panel'))

        self.assertContains(response, 'Firulais')
        self.assertContains(response, reverse('clinica:mascotas'))
        self.assertContains(response, reverse('clinica:mascota_nueva'))
        self.assertNotContains(response, 'Próximamente')


class MascotasPersonalSinDuenoTests(TestCase):

    def test_personal_ve_un_mensaje_y_no_rompe(self):
        personal = get_user_model().objects.create_user(
            username='admin', is_staff=True,
        )
        self.client.force_login(personal)

        for url in (reverse('clinica:mascotas'),
                    reverse('clinica:mascota_nueva')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Sección solo para dueños')
