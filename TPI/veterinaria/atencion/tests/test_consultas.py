from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from administracion.models import Pago
from atencion.models import NivelUrgencia, Turno, Veterinario
from atencion.services.turnos import historial_turnos, proximos_turnos
from clinica.services.mascotas import dar_de_baja_mascota, registrar_mascota
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

# Miercoles 14/10/2026 a las 12:00 (hora de Argentina).
AHORA = datetime(
    2026, 10, 14, 12, 0, tzinfo=ZoneInfo('America/Argentina/Buenos_Aires'),
)


class ConsultasBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_dueno()
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.firulais = registrar_mascota(cls.ana, **datos_mascota())
        cls.michi = registrar_mascota(
            cls.beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )
        cls.veterinario = Veterinario.objects.create(
            nombre='Dra. Laura Gómez', matricula='MP-0001',
            especialidad='CLINICA_GENERAL',
        )
        # Un veterinario no puede tener dos turnos a la misma hora: los
        # turnos del otro dueño van con otro veterinario.
        cls.otro_veterinario = Veterinario.objects.create(
            nombre='Dr. Martín Sosa', matricula='MP-0002',
            especialidad='CARDIOLOGIA',
        )
        cls.urgencia = NivelUrgencia.objects.create(
            sintomas_descripcion='-', nivel_urgencia='BAJA',
        )

    def setUp(self):
        parche = patch('django.utils.timezone.now', return_value=AHORA)
        parche.start()
        self.addCleanup(parche.stop)

    def crear_turno(self, mascota, delta, estado=Turno.Estado.PENDIENTE):
        return Turno.objects.create(
            mascota=mascota,
            veterinario=(
                self.otro_veterinario if mascota == self.michi
                else self.veterinario
            ),
            nivel_urgencia=self.urgencia,
            fecha_hora=AHORA + delta,
            tipo='Consulta Regular',
            estado=estado,
        )


class ProximosEHistorialTests(ConsultasBase):

    def test_proximos_solo_futuros_reservados_del_dueno_en_orden(self):
        lejano = self.crear_turno(self.firulais, timedelta(days=3))
        cercano = self.crear_turno(self.firulais, timedelta(hours=2))
        en_curso = self.crear_turno(
            self.firulais, timedelta(days=1), Turno.Estado.EN_CURSO,
        )
        self.crear_turno(self.firulais, timedelta(days=-1))
        self.crear_turno(
            self.firulais, timedelta(days=2), Turno.Estado.CANCELADO,
        )
        self.crear_turno(self.michi, timedelta(days=1))

        self.assertEqual(
            proximos_turnos(self.ana), [cercano, en_curso, lejano],
        )

    def test_proximos_no_incluye_mascotas_dadas_de_baja(self):
        self.crear_turno(self.firulais, timedelta(days=1))
        dar_de_baja_mascota(self.ana, self.firulais.pk)

        self.assertEqual(proximos_turnos(self.ana), [])

    def test_historial_del_mas_reciente_al_mas_viejo(self):
        viejo = self.crear_turno(
            self.firulais, timedelta(days=-30), Turno.Estado.FINALIZADO,
        )
        reciente = self.crear_turno(self.firulais, timedelta(days=-1))
        cancelado_futuro = self.crear_turno(
            self.firulais, timedelta(days=2), Turno.Estado.CANCELADO,
        )
        self.crear_turno(self.firulais, timedelta(days=1))
        self.crear_turno(self.michi, timedelta(days=-1))

        self.assertEqual(
            historial_turnos(self.ana), [cancelado_futuro, reciente, viejo],
        )

    def test_historial_respeta_el_limite(self):
        for dias in range(1, 13):
            self.crear_turno(self.firulais, timedelta(days=-dias))

        historial = historial_turnos(self.ana)

        self.assertEqual(len(historial), 10)
        self.assertEqual(historial[0].fecha_hora, AHORA - timedelta(days=1))
        self.assertEqual(len(historial_turnos(self.ana, limite=3)), 3)

    def test_personal_sin_dueno_no_tiene_turnos(self):
        self.assertEqual(proximos_turnos(None), [])
        self.assertEqual(historial_turnos(None), [])

    def test_no_hace_una_consulta_por_turno(self):
        for dias in range(1, 6):
            turno = self.crear_turno(self.firulais, timedelta(days=dias))
            Pago.objects.create(
                turno=turno, monto_total=Decimal('1000'),
                monto_cubierto_os=Decimal('0'), metodo='EFECTIVO',
            )

        # 1 consulta para los turnos (con mascota y veterinario) + 1
        # para todos los pagos.
        with self.assertNumQueries(2):
            for turno in proximos_turnos(self.ana):
                turno.mascota.nombre
                turno.veterinario.nombre
                list(turno.pagos.all())


class ConsultasViewTests(ConsultasBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana.usuario)

    def test_sin_sesion_redirige_a_ingresar_con_next(self):
        self.client.logout()
        url = reverse('atencion:consultas')

        response = self.client.get(url)

        self.assertRedirects(
            response, f"{reverse('clinica:ingresar')}?next={url}",
        )

    def test_muestra_los_proximos_turnos_del_dueno(self):
        turno = self.crear_turno(self.firulais, timedelta(days=1, hours=3))
        Pago.objects.create(
            turno=turno, monto_total=Decimal('1000'),
            monto_cubierto_os=Decimal('0'), metodo='EFECTIVO',
        )
        self.crear_turno(self.michi, timedelta(days=1))

        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, 'Mis consultas')
        self.assertContains(response, 'Jueves 15 de octubre')
        self.assertContains(response, '15:00 hs')
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'fa-dog')
        self.assertContains(response, 'Dra. Laura Gómez')
        self.assertContains(response, 'Clínica general')
        self.assertContains(response, 'Pago: Pendiente')
        self.assertNotContains(response, 'Michi')
        self.assertNotContains(response, 'Hoy</span>')
        self.assertContains(
            response, reverse('atencion:turno_cancelar', args=[turno.pk]),
        )

    def test_turno_de_hoy_lleva_el_badge_hoy(self):
        self.crear_turno(self.firulais, timedelta(hours=3))

        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, 'Hoy</span>')

    def test_sin_turnos_muestra_estado_vacio_con_sacar_turno(self):
        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, 'No tenés turnos reservados')
        self.assertContains(response, reverse('atencion:turno_nuevo'))

    def test_historial_muestra_los_turnos_pasados(self):
        self.crear_turno(
            self.firulais, timedelta(days=-5), Turno.Estado.FINALIZADO,
        )

        response = self.client.get(reverse('atencion:consultas'))

        self.assertContains(response, 'Historial (1)')
        self.assertContains(response, '09/10/2026 12:00 hs')
        self.assertContains(response, 'Finalizado')
        self.assertContains(response, 'accordion-button collapsed')

    def test_personal_sin_dueno_ve_un_mensaje_y_no_rompe(self):
        personal = get_user_model().objects.create_user(
            username='admin', is_staff=True,
        )
        self.client.force_login(personal)

        response = self.client.get(reverse('atencion:consultas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sección solo para dueños')
