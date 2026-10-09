from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from clinica.models import Dueno
from clinica.services.usuarios import (
    MENSAJE_DNI_REGISTRADO,
    MENSAJE_EMAIL_EN_USO,
    registrar_dueno,
)

PASSWORD = 'PerroFeliz#2026'


def _datos_registro(**overrides):
    datos = {
        'nombre': 'Juan',
        'apellido': 'Pérez',
        'dni': '30.123.456',
        'email': 'juan@mail.com',
        'telefono': '341 555-1234',
        'password1': PASSWORD,
        'password2': PASSWORD,
    }
    datos.update(overrides)
    return datos


def _crear_dueno(nombre='Ana', email='ana@mail.com', dni='28111222'):
    return registrar_dueno(
        nombre=nombre, apellido='Gómez', dni=dni, email=email,
        telefono='341 555-0000', password=PASSWORD,
    )


class RegistroViewTests(TestCase):

    def test_post_valido_crea_cuenta_inicia_sesion_y_va_al_panel(self):
        response = self.client.post(
            reverse('clinica:registro'), _datos_registro(),
        )

        self.assertRedirects(response, reverse('clinica:panel'))
        dueno = Dueno.objects.get(email='juan@mail.com')
        self.assertEqual(dueno.dni, '30123456')
        self.assertEqual(
            int(self.client.session[SESSION_KEY]), dueno.usuario_id,
        )

    def test_email_repetido_muestra_error_en_el_campo(self):
        _crear_dueno(email='juan@mail.com')

        response = self.client.post(
            reverse('clinica:registro'),
            _datos_registro(email='Juan@Mail.com', dni='40111222'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            MENSAJE_EMAIL_EN_USO, response.context['form'].errors['email'],
        )
        self.assertEqual(Dueno.objects.count(), 1)

    def test_dni_repetido_muestra_error_en_el_campo(self):
        _crear_dueno(dni='30123456')

        response = self.client.post(
            reverse('clinica:registro'), _datos_registro(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            MENSAJE_DNI_REGISTRADO, response.context['form'].errors['dni'],
        )
        self.assertEqual(Dueno.objects.count(), 1)

    def test_dni_con_formato_invalido_muestra_error(self):
        response = self.client.post(
            reverse('clinica:registro'), _datos_registro(dni='123'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('dni', response.context['form'].errors)

    def test_contrasenas_distintas_muestran_error(self):
        response = self.client.post(
            reverse('clinica:registro'),
            _datos_registro(password2='OtraClave#2026'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'Las contraseñas no coinciden.',
            response.context['form'].errors['password2'],
        )
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_contrasena_debil_muestra_error(self):
        response = self.client.post(
            reverse('clinica:registro'),
            _datos_registro(password1='12345678', password2='12345678'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('password1', response.context['form'].errors)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_con_sesion_iniciada_redirige_al_panel(self):
        self.client.force_login(_crear_dueno().usuario)

        response = self.client.get(reverse('clinica:registro'))

        self.assertRedirects(response, reverse('clinica:panel'))


class LoginLogoutTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dueno = _crear_dueno()

    def test_login_correcto_redirige_al_panel(self):
        response = self.client.post(
            reverse('clinica:ingresar'),
            {'username': 'ANA@mail.com', 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('clinica:panel'))
        self.assertEqual(
            int(self.client.session[SESSION_KEY]), self.dueno.usuario_id,
        )

    def test_login_incorrecto_muestra_error_generico(self):
        response = self.client.post(
            reverse('clinica:ingresar'),
            {'username': 'ana@mail.com', 'password': 'incorrecta'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Email o contraseña incorrectos.')
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_por_post_cierra_la_sesion(self):
        self.client.force_login(self.dueno.usuario)

        response = self.client.post(reverse('clinica:salir'))

        self.assertRedirects(response, reverse('core:inicio'))
        self.assertNotIn(SESSION_KEY, self.client.session)
        response = self.client.get(reverse('clinica:panel'))
        self.assertEqual(response.status_code, 302)


class PanelViewTests(TestCase):

    def test_sin_sesion_redirige_al_login_con_next(self):
        url_panel = reverse('clinica:panel')

        response = self.client.get(url_panel)

        self.assertRedirects(
            response, f"{reverse('clinica:ingresar')}?next={url_panel}",
        )

    def test_muestra_datos_del_dueno(self):
        dueno = _crear_dueno()
        self.client.force_login(dueno.usuario)

        response = self.client.get(reverse('clinica:panel'))

        self.assertContains(response, 'Hola, Ana')
        self.assertContains(response, '28111222')
        self.assertContains(response, 'ana@mail.com')
        self.assertContains(response, 'Todavía no registraste mascotas')
        self.assertContains(response, reverse('atencion:triage'))

    def test_personal_sin_dueno_ve_mensaje_y_link_al_admin(self):
        personal = get_user_model().objects.create_user(
            username='admin', password=PASSWORD, is_staff=True,
        )
        self.client.force_login(personal)

        response = self.client.get(reverse('clinica:panel'))

        self.assertContains(response, 'personal de la clínica')
        self.assertContains(response, reverse('admin:index'))


class SesionesIndependientesTests(TestCase):
    """Dos navegadores (ej. ventana normal e incognito) con usuarios
    distintos a la vez: la sesion vive en la cookie de cada cliente,
    no en una variable global."""

    def test_dos_clientes_ven_cada_uno_su_propio_panel(self):
        _crear_dueno(nombre='Ana', email='ana@mail.com', dni='28111222')
        _crear_dueno(nombre='Beto', email='beto@mail.com', dni='29333444')
        navegador_ana = Client()
        navegador_beto = Client()

        self.assertTrue(
            navegador_ana.login(username='ana@mail.com', password=PASSWORD)
        )
        self.assertTrue(
            navegador_beto.login(username='beto@mail.com', password=PASSWORD)
        )

        panel_ana = navegador_ana.get(reverse('clinica:panel'))
        panel_beto = navegador_beto.get(reverse('clinica:panel'))
        self.assertContains(panel_ana, 'Hola, Ana')
        self.assertNotContains(panel_ana, 'Beto')
        self.assertContains(panel_beto, 'Hola, Beto')
        self.assertNotContains(panel_beto, 'Ana')

        navegador_ana.post(reverse('clinica:salir'))
        self.assertContains(
            navegador_beto.get(reverse('clinica:panel')), 'Hola, Beto',
        )
