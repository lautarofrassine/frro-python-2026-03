"""Mi perfil: secciones separadas (datos personales, obra social,
cambiar email y cambiar contraseña) y la tarjeta del inicio."""
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

from administracion.tests.test_obras_sociales import crear_obras_sociales
from clinica.models import Dueno
from clinica.services.usuarios import (
    CuentaError,
    cambiar_email,
    cambiar_password,
)
from clinica.tests.test_mascotas import crear_dueno

URL_PERFIL = reverse('clinica:perfil')
URL_INGRESAR = reverse('clinica:ingresar')
PASSWORD = 'Huellas#Seguras2026'
NUEVA = 'Patitas!Nuevas2027'


class TarjetaPerfilTests(TestCase):

    def test_el_inicio_tiene_mi_perfil_y_no_farmacia(self):
        response = self.client.get(reverse('core:inicio'))

        self.assertContains(response, 'Mi perfil')
        self.assertContains(response, 'bi-person-gear')
        self.assertContains(
            response, 'Gestioná tus datos, tu obra social y tu cuenta.',
        )
        self.assertRegex(
            response.content.decode(),
            rf'href="{URL_PERFIL}"\s+id="tarjeta-perfil"\s+'
            r'class="stretched-link',
        )
        self.assertNotContains(response, 'Farmacia')

    def test_sin_sesion_la_tarjeta_lleva_a_ingresar_con_next(self):
        response = self.client.get(URL_PERFIL)

        self.assertRedirects(
            response, f'{URL_INGRESAR}?next={URL_PERFIL}',
            fetch_redirect_response=False,
        )


class PerfilBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.obras, _ = crear_obras_sociales()
        cls.ana = crear_dueno()
        cls.ana.usuario.set_password(PASSWORD)
        cls.ana.usuario.save()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')

    def setUp(self):
        self.client.force_login(self.ana.usuario)

    def post(self, seccion, **datos):
        return self.client.post(
            URL_PERFIL, {'seccion': seccion, **datos}, follow=True,
        )

    def ana_actual(self):
        return Dueno.objects.select_related('usuario').get(pk=self.ana.pk)


class SeccionesTests(PerfilBase):

    def test_muestra_las_cuatro_secciones_con_su_formulario(self):
        contenido = self.client.get(URL_PERFIL).content.decode()

        for seccion in ('datos', 'obra_social', 'email', 'password'):
            with self.subTest(seccion=seccion):
                self.assertIn(
                    f'name="seccion" value="{seccion}"', contenido,
                )
        self.assertEqual(contenido.count('<form method="post"'), 4 + 1)
        self.assertIn('name="old_password"', contenido)
        self.assertIn('name="new_password2"', contenido)
        self.assertIn('name="nuevo_email"', contenido)
        self.assertRegex(contenido, r'value="28111222"\s+readonly')

    def test_guarda_los_datos_personales(self):
        response = self.post(
            'datos', nombre='Ana María', apellido='Gómez Paz',
            telefono='341 555-1111',
        )

        self.assertRedirects(response, URL_PERFIL)
        self.assertContains(response, 'Se guardaron tus datos personales.')
        ana = self.ana_actual()
        self.assertEqual(ana.nombre, 'Ana María')
        self.assertEqual(ana.telefono, '341 555-1111')
        self.assertEqual(ana.usuario.first_name, 'Ana María')
        self.assertEqual(ana.usuario.last_name, 'Gómez Paz')

    def test_guardar_datos_no_modifica_las_otras_secciones(self):
        self.post('datos', nombre='Ana María', apellido='Gómez',
                  telefono='341 555-1111',
                  # Campos de otras secciones: se ignoran.
                  obra_social=str(self.obras['VetSalud Plus'].pk),
                  numero_afiliado='A-1', nuevo_email='otro@mail.com',
                  password_actual=PASSWORD)

        ana = self.ana_actual()
        self.assertIsNone(ana.obra_social)
        self.assertEqual(ana.numero_afiliado, '')
        self.assertEqual(ana.email, 'ana@mail.com')
        self.assertEqual(ana.usuario.username, 'ana@mail.com')

    def test_guardar_obra_social_no_modifica_los_datos(self):
        vetsalud = self.obras['VetSalud Plus']
        self.post('obra_social', obra_social=str(vetsalud.pk),
                  numero_afiliado='A-1', nombre='Otro', telefono='')

        ana = self.ana_actual()
        self.assertEqual(ana.obra_social, self.obras['VetSalud Plus'])
        self.assertEqual(ana.nombre, 'Ana')
        self.assertEqual(ana.telefono, '341 555-0000')

    def test_el_error_se_muestra_en_su_seccion(self):
        response = self.post('datos', nombre='', apellido='Gómez',
                             telefono='341 555-1111')

        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode()
        datos = contenido.index('id="datos-personales"')
        obra = contenido.index('id="obra-social"')
        error = contenido.index('Este campo es obligatorio')
        self.assertTrue(datos < error < obra)
        self.assertEqual(self.ana_actual().nombre, 'Ana')

    def test_seccion_desconocida_no_cambia_nada(self):
        response = self.post('otra', nombre='X', apellido='Y',
                             telefono='341 555-1111')

        self.assertRedirects(response, URL_PERFIL)
        self.assertEqual(self.ana_actual().nombre, 'Ana')


class CambiarEmailTests(PerfilBase):

    def test_con_la_contrasena_correcta_cambia_todo(self):
        response = self.post(
            'email', nuevo_email='  Ana.Nueva@Mail.com ',
            password_actual=PASSWORD,
        )

        self.assertRedirects(response, URL_PERFIL)
        self.assertContains(response, 'ana.nueva@mail.com')
        ana = self.ana_actual()
        self.assertEqual(ana.email, 'ana.nueva@mail.com')
        self.assertEqual(ana.usuario.email, 'ana.nueva@mail.com')
        self.assertEqual(ana.usuario.username, 'ana.nueva@mail.com')

        self.client.logout()
        response = self.client.post(URL_INGRESAR, {
            'username': 'ana.nueva@mail.com', 'password': PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            int(self.client.session[SESSION_KEY]), self.ana.usuario.pk,
        )
        self.client.logout()
        self.assertFalse(self.client.login(
            username='ana@mail.com', password=PASSWORD,
        ))

    def _sin_cambios(self):
        ana = self.ana_actual()
        self.assertEqual(ana.email, 'ana@mail.com')
        self.assertEqual(ana.usuario.email, '')
        self.assertEqual(ana.usuario.username, 'ana@mail.com')

    def test_contrasena_incorrecta_da_error(self):
        response = self.post(
            'email', nuevo_email='nueva@mail.com', password_actual='mala',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La contraseña actual no es correcta.')
        self._sin_cambios()

    def test_email_en_uso_da_error_aunque_cambien_las_mayusculas(self):
        staff = get_user_model().objects.create_user(
            username='admin', email='Personal@ClinicaVet24.com',
        )
        for email in ('beto@mail.com', 'BETO@Mail.com',
                      'personal@clinicavet24.com', 'ADMIN'):
            with self.subTest(email=email):
                with self.assertRaises(CuentaError) as error:
                    cambiar_email(self.ana_actual(), email, PASSWORD)
                if '@' in email:
                    self.assertEqual(
                        str(error.exception), 'Este email ya está en uso.',
                    )
                self._sin_cambios()
        self.assertTrue(get_user_model().objects.filter(pk=staff.pk).exists())

    def test_email_en_uso_desde_la_pantalla(self):
        response = self.post(
            'email', nuevo_email='Beto@MAIL.com', password_actual=PASSWORD,
        )

        self.assertContains(response, 'Este email ya está en uso.')
        self._sin_cambios()

    def test_email_invalido_o_el_mismo_da_error(self):
        for email in ('no-es-un-email', 'ANA@mail.com'):
            with self.subTest(email=email):
                with self.assertRaises(CuentaError) as error:
                    cambiar_email(self.ana_actual(), email, PASSWORD)
                self.assertEqual(error.exception.campo, 'nuevo_email')
                self._sin_cambios()


class CambiarPasswordTests(PerfilBase):

    def _post(self, actual=PASSWORD, nueva1=NUEVA, nueva2=NUEVA):
        return self.post(
            'password', old_password=actual, new_password1=nueva1,
            new_password2=nueva2,
        )

    def test_la_cambia_hasheada_y_la_sesion_sigue_activa(self):
        response = self._post()

        self.assertRedirects(response, URL_PERFIL)
        self.assertContains(response, 'Se cambió tu contraseña.')
        usuario = self.ana_actual().usuario
        self.assertTrue(usuario.check_password(NUEVA))
        self.assertNotIn(NUEVA, usuario.password)
        self.assertTrue(usuario.password.startswith('pbkdf2_'))
        # Sigue logueada: puede volver a entrar a Mi perfil.
        self.assertEqual(self.client.get(URL_PERFIL).status_code, 200)

    def _sigue_la_anterior(self):
        self.assertTrue(self.ana_actual().usuario.check_password(PASSWORD))

    def test_actual_incorrecta_da_error(self):
        response = self._post(actual='equivocada')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form_password'].errors)
        self.assertIn('old_password', response.context['form_password'].errors)
        self._sigue_la_anterior()

    def test_nuevas_que_no_coinciden_dan_error(self):
        response = self._post(nueva2=NUEVA + 'x')

        self.assertIn(
            'new_password2', response.context['form_password'].errors,
        )
        self._sigue_la_anterior()

    def test_nueva_debil_da_error(self):
        for debil in ('12345678', 'abc', 'ana@mail.com'):
            with self.subTest(debil=debil):
                response = self._post(nueva1=debil, nueva2=debil)
                self.assertTrue(response.context['form_password'].errors)
                self._sigue_la_anterior()

    def test_cambiar_password_no_toca_los_datos(self):
        self._post()

        ana = self.ana_actual()
        self.assertEqual(ana.nombre, 'Ana')
        self.assertEqual(ana.email, 'ana@mail.com')

    def test_service_valida_actual_y_validadores(self):
        usuario = self.ana_actual().usuario
        with self.assertRaises(CuentaError):
            cambiar_password(usuario, 'mala', NUEVA)
        with self.assertRaises(CuentaError):
            cambiar_password(usuario, PASSWORD, '123')
        self.assertTrue(usuario.check_password(PASSWORD))
        cambiar_password(usuario, PASSWORD, NUEVA)
        self.assertTrue(self.ana_actual().usuario.check_password(NUEVA))
