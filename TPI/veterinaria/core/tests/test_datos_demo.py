"""Datos de demostracion. "Hoy" es el miercoles 14/10/2026 a las 10:00."""
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from administracion.models import ObraSocial, Pago
from administracion.services.obras_sociales import (
    asignar_obras_sociales_de_prueba,
    cargar_obras_sociales_iniciales,
)
from administracion.services.pagos import (
    SIN_OBRA_SOCIAL,
    VETERINARIO_NO_ATIENDE,
)
from atencion.models import Turno, Veterinario
from atencion.services.precios import precio_vigente
from atencion.services.turnos import horarios_del_dia
from atencion.services.veterinarios import cargar_veterinarios_iniciales
from clinica.models import AplicacionVacuna, Dueno, HistorialClinico, Mascota
from clinica.services.mascotas import registrar_mascota
from clinica.services.vacunas import cargar_vacunas_iniciales
from clinica.tests.test_mascotas import crear_dueno, datos_mascota
from core.services.datos_demo import (
    DOMINIO,
    EMAIL_PRINCIPAL,
    DatosDemoError,
    borrar_datos_demo,
    cargar_datos_demo,
)

ZONA = ZoneInfo('America/Argentina/Buenos_Aires')
AHORA = datetime(2026, 10, 14, 10, 0, tzinfo=ZONA)
PASSWORD = 'Patitas#Demo2026'
# El hash de verdad (PBKDF2) haria lentos estos tests.
HASHER_RAPIDO = ['django.contrib.auth.hashers.MD5PasswordHasher']


@override_settings(PASSWORD_HASHERS=HASHER_RAPIDO)
class DatosDemoBase(TestCase):
    """Lo que ya esta cargado en la clinica: veterinarios con horarios
    (y la cuenta de Laura), obras sociales asignadas y vacunas."""

    @classmethod
    def setUpTestData(cls):
        cargar_veterinarios_iniciales()
        cargar_obras_sociales_iniciales()
        asignar_obras_sociales_de_prueba()
        cargar_vacunas_iniciales()
        cls.laura = Veterinario.objects.get(matricula='MP-5001')
        cls.laura.usuario = get_user_model().objects.create_user(
            username='laura.fernandez@clinicavet24.com',
            email='laura.fernandez@clinicavet24.com',
        )
        cls.laura.save()

    def setUp(self):
        parche = patch('django.utils.timezone.now', return_value=AHORA)
        parche.start()
        self.addCleanup(parche.stop)

    def cargar(self):
        return cargar_datos_demo(PASSWORD)


class CantidadesTests(DatosDemoBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with patch('django.utils.timezone.now', return_value=AHORA):
            cls.resumen = cargar_datos_demo(PASSWORD)

    def test_duenos_y_mascotas(self):
        duenos = Dueno.objects.filter(email__endswith=DOMINIO)
        self.assertEqual(duenos.count(), 15)
        self.assertEqual(duenos.exclude(obra_social=None).count(), 10)
        self.assertFalse(
            duenos.exclude(obra_social=None)
            .filter(numero_afiliado='').exists()
        )
        self.assertTrue(
            duenos.filter(obra_social__porcentaje_cobertura=100).exists()
        )
        self.assertEqual(len(set(duenos.values_list('dni', flat=True))), 15)
        self.assertTrue(all(
            len(dni) == 8 for dni in duenos.values_list('dni', flat=True)
        ))
        mascotas = Mascota.objects.filter(dueno__in=duenos)
        self.assertEqual(mascotas.count(), 27)
        self.assertEqual(
            set(mascotas.values_list('especie', flat=True)),
            {'PERRO', 'GATO'},
        )
        cachorros = mascotas.filter(
            fecha_nacimiento__gt=AHORA.date() - timedelta(days=180),
        )
        self.assertGreaterEqual(cachorros.count(), 3)
        # Los dueños pueden ingresar con DEMO_PASSWORD.
        self.assertTrue(self.client.login(
            username=EMAIL_PRINCIPAL, password=PASSWORD,
        ))

    def test_turnos_futuros(self):
        futuros = Turno.objects.filter(
            mascota__dueno__email__endswith=DOMINIO,
            fecha_hora__gt=AHORA,
        )
        reservados = futuros.exclude(estado=Turno.Estado.CANCELADO)
        self.assertEqual(reservados.count(), 40)
        self.assertEqual(self.resumen['turnos_futuros'], 40)
        self.assertTrue(all(
            t.fecha_hora <= AHORA + timedelta(days=14) for t in reservados
        ))
        guardia = reservados.filter(tipo='Guardia')
        self.assertEqual(guardia.count(), 3)
        self.assertEqual(
            set(guardia.values_list('nivel_urgencia__nivel_urgencia',
                                    flat=True)),
            {'CRITICA', 'ALTA'},
        )
        vacunacion = reservados.exclude(vacuna=None).select_related(
            'vacuna', 'mascota',
        )
        self.assertEqual(vacunacion.count(), 8)
        self.assertTrue(all(
            t.vacuna.especie == t.mascota.especie for t in vacunacion
        ))
        especialidades = set(
            reservados.values_list('veterinario__especialidad', flat=True)
        )
        self.assertGreaterEqual(len(especialidades), 6)
        pagados = Pago.objects.filter(
            turno__in=reservados, estado=Pago.Estado.PAGADO,
        )
        self.assertEqual(pagados.count(), 8)
        self.assertFalse(pagados.filter(numero_comprobante=None).exists())
        self.assertEqual(
            set(pagados.values_list('metodo', flat=True)),
            {'MERCADO_PAGO', 'EFECTIVO'},
        )

    def test_turnos_pasados_con_historia_dentro_del_horario(self):
        pasados = Turno.objects.filter(
            mascota__dueno__email__endswith=DOMINIO, fecha_hora__lt=AHORA,
        ).select_related('veterinario')
        self.assertEqual(pasados.count(), 30)
        for turno in pasados:
            with self.subTest(turno=turno.pk):
                self.assertEqual(turno.estado, Turno.Estado.FINALIZADO)
                self.assertGreaterEqual(
                    turno.fecha_hora, AHORA - timedelta(days=61),
                )
                dia = timezone.localtime(turno.fecha_hora).date()
                self.assertIn(
                    turno.fecha_hora,
                    horarios_del_dia(turno.veterinario, dia),
                )
                self.assertIn(
                    turno.pagos.get().estado,
                    (Pago.Estado.PAGADO, Pago.Estado.CUBIERTO_OS),
                )
                entrada = turno.entradas_historia.get()
                self.assertEqual(entrada.veterinario, turno.veterinario)
                self.assertTrue(entrada.diagnostico)
                self.assertTrue(entrada.tratamiento)
                self.assertTrue(entrada.observaciones)
        self.assertEqual(
            HistorialClinico.objects.filter(
                mascota__dueno__email__endswith=DOMINIO,
            ).count(),
            30,
        )
        self.assertEqual(self.resumen['historias'], 30)

    def test_vacunas_aplicadas_coherentes(self):
        aplicaciones = AplicacionVacuna.objects.filter(
            mascota__dueno__email__endswith=DOMINIO,
        ).select_related('mascota', 'vacuna')
        self.assertGreaterEqual(aplicaciones.count(), 10)
        for aplicacion in aplicaciones:
            with self.subTest(aplicacion=aplicacion.pk):
                self.assertEqual(
                    aplicacion.vacuna.especie, aplicacion.mascota.especie,
                )
                self.assertLess(aplicacion.fecha_aplicacion, AHORA.date())
                self.assertGreaterEqual(
                    (aplicacion.fecha_aplicacion
                     - aplicacion.mascota.fecha_nacimiento).days,
                    60,
                )

    def test_agenda_de_laura(self):
        manana = AHORA.date() + timedelta(days=1)
        proximos = Turno.objects.filter(
            veterinario=self.laura, fecha_hora__gt=AHORA,
            fecha_hora__date__lte=manana,
        )
        self.assertGreaterEqual(proximos.count(), 3)
        self.assertTrue(
            HistorialClinico.objects.filter(veterinario=self.laura).exists()
        )

    def test_dueno_principal(self):
        principal = Dueno.objects.get(email=EMAIL_PRINCIPAL)
        self.assertIsNotNone(principal.obra_social)
        self.assertEqual(principal.mascotas.count(), 3)
        turnos = Turno.objects.filter(mascota__dueno=principal)
        self.assertTrue(turnos.filter(fecha_hora__gt=AHORA).exists())
        self.assertTrue(turnos.filter(fecha_hora__lt=AHORA).exists())
        self.assertTrue(HistorialClinico.objects.filter(
            mascota__dueno=principal,
        ).exists())
        self.assertTrue(AplicacionVacuna.objects.filter(
            mascota__dueno=principal,
        ).exists())
        estados = set(Pago.objects.filter(
            turno__mascota__dueno=principal,
        ).values_list('estado', flat=True))
        self.assertTrue({'PENDIENTE', 'PAGADO', 'CANCELADO',
                         'REEMBOLSADO'} <= estados)

    def test_pagos_con_la_cobertura_correcta(self):
        pagos = Pago.objects.filter(
            turno__mascota__dueno__email__endswith=DOMINIO,
        ).select_related(
            'turno__veterinario', 'turno__mascota__dueno__obra_social',
        )
        casos = set()
        for pago in pagos:
            turno = pago.turno
            dueno = turno.mascota.dueno
            with self.subTest(pago=pago.pk):
                self.assertEqual(
                    pago.monto_total,
                    precio_vigente(turno.veterinario, turno.fecha_hora),
                )
                self.assertEqual(
                    pago.monto_cubierto_os + pago.monto_a_pagar,
                    pago.monto_total,
                )
                if dueno.obra_social is None:
                    self.assertEqual(pago.monto_cubierto_os, 0)
                    self.assertEqual(pago.detalle_cobertura, SIN_OBRA_SOCIAL)
                    casos.add('sin_obra_social')
                elif not turno.veterinario.obras_sociales.filter(
                        pk=dueno.obra_social_id).exists():
                    self.assertEqual(pago.monto_cubierto_os, 0)
                    self.assertEqual(
                        pago.detalle_cobertura, VETERINARIO_NO_ATIENDE,
                    )
                    casos.add('no_atiende')
                elif pago.monto_cubierto_os:
                    esperado = (
                        pago.monto_total
                        * dueno.obra_social.porcentaje_cobertura / 100
                    ).quantize(Decimal('0.01'))
                    # Igual al porcentaje, salvo que lo limite el tope.
                    self.assertLessEqual(pago.monto_cubierto_os, esperado)
                    casos.add(
                        'total' if pago.monto_a_pagar == 0 else 'parcial'
                    )
        self.assertEqual(
            casos, {'sin_obra_social', 'no_atiende', 'total', 'parcial'},
        )
        self.assertTrue(pagos.filter(estado=Pago.Estado.CUBIERTO_OS).exists())


class IdempotenciaYBorradoTests(DatosDemoBase):

    def test_correrlo_dos_veces_no_duplica(self):
        self.cargar()
        cantidades = (
            Dueno.objects.count(), Mascota.objects.count(),
            Turno.objects.count(), Pago.objects.count(),
            HistorialClinico.objects.count(),
            AplicacionVacuna.objects.count(),
        )

        resumen = self.cargar()

        self.assertTrue(resumen['ya_cargados'])
        self.assertEqual(cantidades, (
            Dueno.objects.count(), Mascota.objects.count(),
            Turno.objects.count(), Pago.objects.count(),
            HistorialClinico.objects.count(),
            AplicacionVacuna.objects.count(),
        ))

    def test_borrar_elimina_solo_lo_de_demo(self):
        ajeno = crear_dueno('real@mail.com', '20111222', 'Real')
        mascota_ajena = registrar_mascota(ajeno, **datos_mascota())
        usuarios_antes = get_user_model().objects.count()
        veterinarios = Veterinario.objects.count()
        obras = ObraSocial.objects.count()
        self.cargar()

        borrado = borrar_datos_demo()

        self.assertEqual(borrado['duenos'], 15)
        self.assertEqual(borrado['mascotas'], 27)
        self.assertFalse(Dueno.objects.filter(
            email__endswith=DOMINIO,
        ).exists())
        self.assertFalse(Turno.objects.exists())
        self.assertFalse(Pago.objects.exists())
        self.assertFalse(HistorialClinico.objects.exists())
        self.assertFalse(AplicacionVacuna.objects.exists())
        self.assertEqual(list(Dueno.objects.all()), [ajeno])
        self.assertTrue(Mascota.objects.filter(pk=mascota_ajena.pk).exists())
        self.assertEqual(get_user_model().objects.count(), usuarios_antes)
        self.assertEqual(Veterinario.objects.count(), veterinarios)
        self.assertEqual(ObraSocial.objects.count(), obras)
        # Despues de borrar se puede volver a cargar.
        self.assertFalse(self.cargar()['ya_cargados'])

    def test_sin_contrasena_falla_con_un_mensaje_claro(self):
        with self.assertRaisesMessage(DatosDemoError, 'DEMO_PASSWORD'):
            cargar_datos_demo('')
        with patch.dict('os.environ', {'DEMO_PASSWORD': ''}):
            with self.assertRaisesMessage(CommandError, 'DEMO_PASSWORD'):
                call_command('cargar_datos_demo', stdout=StringIO())
        self.assertFalse(Dueno.objects.exists())

    def test_el_comando_carga_borra_y_muestra_el_resumen(self):
        salida = StringIO()
        with patch.dict('os.environ', {'DEMO_PASSWORD': PASSWORD}):
            call_command('cargar_datos_demo', stdout=salida)
            call_command('cargar_datos_demo', stdout=salida)
        texto = salida.getvalue()
        self.assertIn('Dueños: 15', texto)
        self.assertIn('Mascotas: 27', texto)
        self.assertIn('40 futuros, 30 pasados', texto)
        self.assertIn('Entradas de historia clínica: 30', texto)
        self.assertIn(EMAIL_PRINCIPAL, texto)
        self.assertIn('laura.fernandez@clinicavet24.com', texto)
        self.assertNotIn(PASSWORD, texto)
        self.assertIn('ya estaban cargados', texto)

        salida = StringIO()
        call_command('cargar_datos_demo', '--borrar', stdout=salida)
        self.assertIn('15 dueños', salida.getvalue())
        self.assertFalse(Dueno.objects.exists())


@override_settings(PASSWORD_HASHERS=HASHER_RAPIDO)
class RequisitosTests(TestCase):

    def test_sin_veterinarios_ni_obras_sociales_avisa_que_cargar(self):
        with self.assertRaises(DatosDemoError) as error:
            cargar_datos_demo(PASSWORD)

        mensaje = str(error.exception)
        self.assertIn('cargar_veterinarios', mensaje)
        self.assertIn('cargar_obras_sociales', mensaje)
        self.assertIn('cargar_vacunas', mensaje)
        self.assertFalse(Dueno.objects.exists())
