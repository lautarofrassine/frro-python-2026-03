from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from clinica.models import Dueno
from clinica.services.usuarios import (
    MENSAJE_DNI_REGISTRADO,
    MENSAJE_EMAIL_EN_USO,
    RegistroError,
    obtener_dueno_de_usuario,
    registrar_dueno,
)

PASSWORD = 'PerroFeliz#2026'


def _registrar(**overrides):
    datos = {
        'nombre': 'Juan',
        'apellido': 'Pérez',
        'dni': '30123456',
        'email': 'juan@mail.com',
        'telefono': '341 555-1234',
        'password': PASSWORD,
    }
    datos.update(overrides)
    return registrar_dueno(**datos)


class RegistrarDuenoTests(TestCase):

    def test_crea_user_y_dueno_vinculados(self):
        dueno = _registrar(email='  Juan@Mail.COM ', dni='30.123.456')

        self.assertIsNotNone(dueno.pk)
        self.assertEqual(dueno.email, 'juan@mail.com')
        self.assertEqual(dueno.dni, '30123456')
        self.assertEqual(dueno.usuario.username, 'juan@mail.com')
        self.assertEqual(dueno.usuario.email, 'juan@mail.com')
        self.assertEqual(dueno.usuario.first_name, 'Juan')
        self.assertEqual(dueno.usuario.last_name, 'Pérez')
        self.assertEqual(dueno.usuario.dueno, dueno)

    def test_password_se_guarda_hasheada_con_pbkdf2(self):
        dueno = _registrar()
        usuario = get_user_model().objects.get(pk=dueno.usuario_id)

        self.assertTrue(usuario.password.startswith('pbkdf2_sha256$'))
        self.assertNotIn(PASSWORD, usuario.password)
        self.assertTrue(usuario.check_password(PASSWORD))

    def test_dueno_no_guarda_la_password_en_ningun_campo(self):
        dueno = _registrar()

        nombres_campos = [f.name for f in Dueno._meta.concrete_fields]
        self.assertFalse(
            any('pass' in nombre or 'contra' in nombre
                for nombre in nombres_campos)
        )
        for campo in Dueno._meta.concrete_fields:
            self.assertNotIn(PASSWORD, str(campo.value_from_object(dueno)))

    def test_email_repetido_no_crea_nada(self):
        _registrar()
        users_antes = get_user_model().objects.count()

        with self.assertRaisesMessage(RegistroError, MENSAJE_EMAIL_EN_USO):
            _registrar(dni='40111222')

        self.assertEqual(get_user_model().objects.count(), users_antes)
        self.assertEqual(Dueno.objects.count(), 1)

    def test_email_repetido_con_otras_mayusculas_no_crea_nada(self):
        _registrar(email='Juan@Mail.com')
        users_antes = get_user_model().objects.count()

        with self.assertRaisesMessage(RegistroError, MENSAJE_EMAIL_EN_USO):
            _registrar(email='juan@mail.com', dni='40111222')

        self.assertEqual(get_user_model().objects.count(), users_antes)
        self.assertEqual(Dueno.objects.count(), 1)

    def test_email_de_personal_de_la_clinica_tambien_cuenta_como_en_uso(self):
        get_user_model().objects.create_user(
            username='vet', email='vet@clinica.com', password=PASSWORD,
        )

        with self.assertRaisesMessage(RegistroError, MENSAJE_EMAIL_EN_USO):
            _registrar(email='VET@clinica.com')

        self.assertEqual(Dueno.objects.count(), 0)

    def test_dni_repetido_no_crea_nada(self):
        _registrar()
        users_antes = get_user_model().objects.count()

        with self.assertRaisesMessage(RegistroError, MENSAJE_DNI_REGISTRADO):
            _registrar(email='otra@mail.com', dni='30.123.456')

        self.assertEqual(get_user_model().objects.count(), users_antes)
        self.assertEqual(Dueno.objects.count(), 1)

    def test_registro_simultaneo_no_deja_user_sin_dueno(self):
        # Simula la carrera: las verificaciones previas no ven el DNI
        # duplicado, y la restriccion UNIQUE de la base lo rechaza
        # recien al crear el Dueno (con el User ya creado).
        _registrar()
        users_antes = get_user_model().objects.count()

        with patch('clinica.services.usuarios.dni_registrado',
                   return_value=False):
            with self.assertRaises(RegistroError):
                _registrar(email='otra@mail.com')

        self.assertEqual(get_user_model().objects.count(), users_antes)
        self.assertFalse(
            get_user_model().objects.filter(username='otra@mail.com').exists()
        )


class ObtenerDuenoDeUsuarioTests(TestCase):

    def test_devuelve_el_dueno_del_usuario(self):
        dueno = _registrar()

        self.assertEqual(obtener_dueno_de_usuario(dueno.usuario), dueno)

    def test_personal_de_la_clinica_no_tiene_dueno(self):
        personal = get_user_model().objects.create_user(
            username='admin', password=PASSWORD, is_staff=True,
        )

        self.assertIsNone(obtener_dueno_de_usuario(personal))

    def test_usuario_anonimo_no_tiene_dueno(self):
        self.assertIsNone(obtener_dueno_de_usuario(AnonymousUser()))
