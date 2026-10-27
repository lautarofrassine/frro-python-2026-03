import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from atencion.models import Veterinario
from atencion.services.veterinarios import (
    CuentaVeterinarioError,
    crear_usuarios_veterinarios,
    obtener_veterinario_de_usuario,
)

PASSWORD = 'GuardiaSegura#2026'


def _veterinario(nombre, matricula, especialidad='CLINICA_GENERAL',
                 estado='ACTIVO'):
    return Veterinario.objects.create(
        nombre=nombre, matricula=matricula, especialidad=especialidad,
        estado=estado,
    )


class CrearUsuariosVeterinariosTests(TestCase):

    def setUp(self):
        self.laura = _veterinario('Dra. Laura Fernández', 'MP-5001')
        self.acosta = _veterinario(
            'Dr. Federico Acosta', 'MP-5004', 'CARDIOLOGIA',
        )

    def test_crea_un_usuario_por_veterinario_con_email_y_password_hasheada(
        self,
    ):
        creados = crear_usuarios_veterinarios(PASSWORD)

        self.assertEqual(len(creados), 2)
        self.laura.refresh_from_db()
        usuario = self.laura.usuario
        self.assertEqual(usuario.username, 'laura.fernandez@clinicavet24.com')
        self.assertEqual(usuario.email, 'laura.fernandez@clinicavet24.com')
        self.assertEqual(usuario.first_name, 'Laura')
        self.assertEqual(usuario.last_name, 'Fernández')
        self.assertTrue(usuario.password.startswith('pbkdf2_sha256$'))
        self.assertNotIn(PASSWORD, usuario.password)
        self.assertTrue(usuario.check_password(PASSWORD))
        self.assertFalse(usuario.is_staff)
        self.assertEqual(
            Veterinario.objects.get(pk=self.acosta.pk).usuario.email,
            'federico.acosta@clinicavet24.com',
        )
        self.assertEqual(obtener_veterinario_de_usuario(usuario), self.laura)

    def test_si_el_email_se_repite_agrega_un_numero(self):
        _veterinario('Dra. Laura Fernández', 'MP-6001', 'DERMATOLOGIA')
        get_user_model().objects.create_user(
            username='federico.acosta@clinicavet24.com',
        )

        crear_usuarios_veterinarios(PASSWORD)

        emails = sorted(
            Veterinario.objects.values_list('usuario__email', flat=True)
        )
        self.assertEqual(emails, [
            'federico.acosta2@clinicavet24.com',
            'laura.fernandez2@clinicavet24.com',
            'laura.fernandez@clinicavet24.com',
        ])

    def test_no_duplica_ni_toca_a_los_que_ya_tienen_usuario(self):
        crear_usuarios_veterinarios(PASSWORD)
        usuarios_antes = get_user_model().objects.count()
        hash_antes = Veterinario.objects.get(pk=self.laura.pk).usuario.password

        creados = crear_usuarios_veterinarios('OtraClaveDistinta#2026')

        self.assertEqual(creados, [])
        self.assertEqual(get_user_model().objects.count(), usuarios_antes)
        self.assertEqual(
            Veterinario.objects.get(pk=self.laura.pk).usuario.password,
            hash_antes,
        )

    def test_no_crea_cuenta_a_los_inactivos(self):
        inactivo = _veterinario(
            'Dr. Inactivo Gómez', 'MP-9999', estado='INACTIVO',
        )

        crear_usuarios_veterinarios(PASSWORD)

        inactivo.refresh_from_db()
        self.assertIsNone(inactivo.usuario)

    def test_sin_password_o_con_una_debil_falla_sin_crear_nada(self):
        for password in ('', None, '12345678'):
            with self.subTest(password=password):
                with self.assertRaises(CuentaVeterinarioError):
                    crear_usuarios_veterinarios(password)
        self.assertEqual(get_user_model().objects.count(), 0)


class ComandoCrearUsuariosVeterinariosTests(TestCase):

    def setUp(self):
        _veterinario('Dra. Laura Fernández', 'MP-5001')

    def test_sin_la_variable_de_entorno_falla_con_un_mensaje_claro(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VET_PASSWORD_INICIAL', None)
            with self.assertRaisesMessage(
                CommandError, 'VET_PASSWORD_INICIAL',
            ):
                call_command(
                    'crear_usuarios_veterinarios', stdout=StringIO(),
                )

        self.assertEqual(get_user_model().objects.count(), 0)

    def test_imprime_la_tabla_sin_contrasenas(self):
        salida = StringIO()

        with patch.dict(os.environ, {'VET_PASSWORD_INICIAL': PASSWORD}):
            call_command('crear_usuarios_veterinarios', stdout=salida)
            call_command('crear_usuarios_veterinarios', stdout=StringIO())

        texto = salida.getvalue()
        self.assertIn('Dra. Laura Fernández', texto)
        self.assertIn('Clínica general', texto)
        self.assertIn('laura.fernandez@clinicavet24.com  (nueva)', texto)
        self.assertIn('Cuentas creadas: 1. Ya existían: 0.', texto)
        self.assertNotIn(PASSWORD, texto)
        self.assertEqual(get_user_model().objects.count(), 1)
