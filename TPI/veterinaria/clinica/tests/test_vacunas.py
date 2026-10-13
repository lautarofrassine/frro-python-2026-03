import html
import re
from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from atencion.models import HorarioAtencion, NivelUrgencia, Turno, Veterinario
from clinica.models import Vacuna
from clinica.services.mascotas import MascotaNoEncontrada, registrar_mascota
from clinica.services.vacunas import (
    TurnoVacunaNoEncontrado,
    VacunaError,
    calendario_vacunacion,
    cargar_vacunas_iniciales,
    detalle_turno_vacuna,
    horarios_libres_vacunacion,
    reservar_turno_vacuna,
    turnos_vacunacion_del_mes,
    vacunas_para_mascota,
)
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

ZONA = ZoneInfo('America/Argentina/Buenos_Aires')
# Miercoles 14/10/2026 a las 12:00 (hora de Argentina).
AHORA = datetime(2026, 10, 14, 12, 0, tzinfo=ZONA)


def _veterinario(nombre, matricula, especialidad, inicio, fin):
    veterinario = Veterinario.objects.create(
        nombre=nombre, matricula=matricula, especialidad=especialidad,
    )
    HorarioAtencion.objects.bulk_create([
        HorarioAtencion(
            veterinario=veterinario, dia_semana=dia,
            hora_inicio=inicio, hora_fin=fin,
        )
        for dia in range(6)
    ])
    return veterinario


class CargarVacunasTests(TestCase):

    def test_crea_3_de_perro_y_3_de_gato(self):
        resumen = cargar_vacunas_iniciales()

        self.assertEqual(resumen, {'creadas': 6, 'existentes': 0})
        self.assertEqual(Vacuna.objects.filter(especie='PERRO').count(), 3)
        self.assertEqual(Vacuna.objects.filter(especie='GATO').count(), 3)
        for vacuna in Vacuna.objects.all():
            with self.subTest(vacuna=str(vacuna)):
                self.assertLessEqual(len(vacuna.nombre_corto), 15)
                self.assertTrue(vacuna.descripcion)
                self.assertEqual(vacuna.periodicidad_dias, 365)

    def test_correrlo_dos_veces_no_duplica(self):
        cargar_vacunas_iniciales()

        resumen = cargar_vacunas_iniciales()

        self.assertEqual(resumen, {'creadas': 0, 'existentes': 6})
        self.assertEqual(Vacuna.objects.count(), 6)
        self.assertEqual(
            Vacuna.objects.filter(nombre='Antirrábica').count(), 2,
        )

    def test_comando_muestra_el_resumen(self):
        salida = StringIO()

        call_command('cargar_vacunas', stdout=salida)

        self.assertIn('6 creadas, 0 ya existían', salida.getvalue())


class VacunasBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cargar_vacunas_iniciales()
        cls.sextuple = Vacuna.objects.get(nombre='Séxtuple')
        cls.triple_felina = Vacuna.objects.get(nombre='Triple felina')
        cls.urgencia = NivelUrgencia.objects.create(
            sintomas_descripcion='-', nivel_urgencia='BAJA',
        )
        # Vacunacion atiende de tarde; el de clinica general, de mañana.
        cls.vacunadora = _veterinario(
            'Dra. Paula Navarro', 'MP-5019', 'VACUNACION',
            time(13, 0), time(19, 0),
        )
        cls.clinico = _veterinario(
            'Dr. Martín Sosa', 'MP-5002', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )
        cls.ana = crear_dueno()
        cls.firulais = registrar_mascota(cls.ana, **datos_mascota())
        cls.luna = registrar_mascota(
            cls.ana, **datos_mascota(nombre='Luna', especie='GATO'),
        )
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.michi = registrar_mascota(
            cls.beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        parche = patch('django.utils.timezone.now', return_value=AHORA)
        parche.start()
        self.addCleanup(parche.stop)

    def crear_turno(self, mascota, cuando, vacuna=None, estado='PENDIENTE'):
        return Turno.objects.create(
            mascota=mascota,
            veterinario=self.vacunadora if vacuna else self.clinico,
            nivel_urgencia=self.urgencia,
            vacuna=vacuna,
            fecha_hora=cuando,
            tipo='Vacunación' if vacuna else 'Consulta Regular',
            estado=estado,
        )


class ReservarVacunaTests(VacunasBase):

    def test_vacunas_para_mascota_son_solo_de_su_especie(self):
        nombres = [v.nombre for v in vacunas_para_mascota(self.luna)]

        self.assertEqual(
            nombres, ['Antirrábica', 'Leucemia felina', 'Triple felina'],
        )

    def test_horarios_libres_son_solo_de_veterinarios_de_vacunacion(self):
        horarios = horarios_libres_vacunacion()

        self.assertEqual(len(horarios), 10)
        self.assertEqual(
            {h['veterinario_id'] for h in horarios}, {self.vacunadora.pk},
        )
        self.assertEqual(
            horarios[0]['fecha_hora'], AHORA.replace(hour=13),
        )

    def test_reservar_marca_el_turno_con_la_vacuna_y_lo_deja_ocupado(self):
        horario = horarios_libres_vacunacion()[0]

        turno = reservar_turno_vacuna(
            self.ana, self.luna.pk, self.triple_felina.pk,
            horario['veterinario_id'], horario['fecha_hora'].isoformat(),
        )

        turno.refresh_from_db()
        self.assertEqual(turno.vacuna, self.triple_felina)
        self.assertEqual(turno.mascota, self.luna)
        self.assertEqual(turno.veterinario, self.vacunadora)
        self.assertEqual(turno.tipo, 'Vacunación')
        self.assertEqual(turno.estado, Turno.Estado.PENDIENTE)
        self.assertEqual(turno.fecha_hora, horario['fecha_hora'])
        self.assertNotIn(
            horario['fecha_hora'],
            [h['fecha_hora'] for h in horarios_libres_vacunacion()],
        )
        # La reserva pasa por reservar_turno, que crea el pago.
        pago = turno.pagos.get()
        self.assertEqual(pago.estado, 'PENDIENTE')
        self.assertEqual(pago.monto_total, 12000)

    def test_un_gato_no_puede_reservar_una_vacuna_de_perro(self):
        horario = horarios_libres_vacunacion()[0]

        with self.assertRaises(VacunaError):
            reservar_turno_vacuna(
                self.ana, self.luna.pk, self.sextuple.pk,
                horario['veterinario_id'], horario['fecha_hora'],
            )

        self.assertEqual(Turno.objects.count(), 0)

    def test_no_se_puede_reservar_un_horario_ya_ocupado(self):
        horario = horarios_libres_vacunacion()[0]
        argumentos = (horario['veterinario_id'], horario['fecha_hora'])
        reservar_turno_vacuna(
            self.ana, self.luna.pk, self.triple_felina.pk, *argumentos,
        )

        with self.assertRaises(VacunaError):
            reservar_turno_vacuna(
                self.ana, self.firulais.pk, self.sextuple.pk, *argumentos,
            )

        self.assertEqual(Turno.objects.count(), 1)

    def test_no_se_puede_reservar_con_un_veterinario_de_otra_especialidad(
        self,
    ):
        with self.assertRaises(VacunaError):
            reservar_turno_vacuna(
                self.ana, self.luna.pk, self.triple_felina.pk,
                self.clinico.pk, AHORA.replace(hour=13),
            )

        self.assertEqual(Turno.objects.count(), 0)

    def test_no_se_puede_reservar_para_la_mascota_de_otro_dueno(self):
        horario = horarios_libres_vacunacion()[0]

        with self.assertRaises(MascotaNoEncontrada):
            reservar_turno_vacuna(
                self.ana, self.michi.pk, self.triple_felina.pk,
                horario['veterinario_id'], horario['fecha_hora'],
            )

        self.assertEqual(Turno.objects.count(), 0)


class CalendarioServiceTests(VacunasBase):

    def test_turnos_del_mes_solo_de_esa_mascota_ese_mes_y_con_vacuna(self):
        dia_20 = datetime(2026, 10, 20, 15, 0, tzinfo=ZONA)
        esperado = self.crear_turno(self.luna, dia_20, self.triple_felina)
        self.crear_turno(
            self.luna, dia_20 + timedelta(days=30), self.triple_felina,
        )
        self.crear_turno(
            self.firulais, dia_20 + timedelta(minutes=30), self.sextuple,
        )
        self.crear_turno(
            self.michi, dia_20 + timedelta(hours=1), self.triple_felina,
        )
        self.crear_turno(self.luna, dia_20 + timedelta(days=1))
        self.crear_turno(
            self.luna, dia_20 + timedelta(days=2), self.triple_felina,
            estado='CANCELADO',
        )

        turnos = turnos_vacunacion_del_mes(self.ana, self.luna.pk, 2026, 10)

        self.assertEqual(turnos, [esperado])

    def test_turnos_del_mes_de_mascota_ajena_no_la_encuentra(self):
        with self.assertRaises(MascotaNoEncontrada):
            turnos_vacunacion_del_mes(self.ana, self.michi.pk, 2026, 10)

    def test_calendario_va_de_domingo_a_sabado_y_marca_hoy(self):
        calendario = calendario_vacunacion(self.ana, self.luna.pk, '2026-10')

        primera_semana = calendario['semanas'][0]
        self.assertEqual(primera_semana[0]['fecha'], date(2026, 9, 27))
        self.assertFalse(primera_semana[0]['del_mes'])
        self.assertEqual(primera_semana[4]['fecha'], date(2026, 10, 1))
        self.assertTrue(primera_semana[4]['del_mes'])
        dias_de_hoy = [
            dia['fecha']
            for semana in calendario['semanas'] for dia in semana
            if dia['es_hoy']
        ]
        self.assertEqual(dias_de_hoy, [date(2026, 10, 14)])
        self.assertEqual(calendario['mes_anterior'], '2026-09')
        self.assertEqual(calendario['mes_siguiente'], '2026-11')

    def test_calendario_sin_mes_o_con_mes_invalido_usa_el_actual(self):
        for texto in (None, '', 'abc', '2026-13'):
            with self.subTest(texto=texto):
                calendario = calendario_vacunacion(
                    self.ana, self.luna.pk, texto,
                )
                self.assertEqual(calendario['primer_dia'], date(2026, 10, 1))

    def test_detalle_de_turno_de_otro_dueno_no_lo_encuentra(self):
        turno = self.crear_turno(
            self.michi, AHORA + timedelta(days=1), self.triple_felina,
        )

        with self.assertRaises(TurnoVacunaNoEncontrado):
            detalle_turno_vacuna(self.ana, turno.pk)
        self.assertEqual(detalle_turno_vacuna(self.beto, turno.pk), turno)

    def test_detalle_de_una_consulta_comun_no_lo_encuentra(self):
        consulta = self.crear_turno(self.luna, AHORA + timedelta(days=1))

        with self.assertRaises(TurnoVacunaNoEncontrado):
            detalle_turno_vacuna(self.ana, consulta.pk)


class VacunasViewsTests(VacunasBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana.usuario)

    def _dia(self, response, fecha):
        return next(
            dia
            for semana in response.context['calendario']['semanas']
            for dia in semana if dia['fecha'] == fecha
        )

    def test_sin_sesion_todo_redirige_a_ingresar(self):
        self.client.logout()
        turno = self.crear_turno(
            self.luna, AHORA + timedelta(days=1), self.triple_felina,
        )
        urls = [
            reverse('clinica:vacunas'),
            reverse('clinica:vacuna_reservar'),
            reverse('clinica:vacuna_turno', args=[turno.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('clinica:ingresar')}?next={url}",
                )

    def test_calendario_muestra_la_etiqueta_en_el_dia_correcto(self):
        dia_20 = datetime(2026, 10, 20, 15, 0, tzinfo=ZONA)
        turno = self.crear_turno(self.luna, dia_20, self.triple_felina)
        self.crear_turno(
            self.luna, dia_20 + timedelta(days=30), self.triple_felina,
        )
        self.crear_turno(
            self.firulais, dia_20 + timedelta(minutes=30), self.sextuple,
        )
        self.crear_turno(
            self.michi, dia_20 + timedelta(hours=1), self.triple_felina,
        )
        self.crear_turno(self.luna, dia_20 + timedelta(days=1))

        response = self.client.get(
            reverse('clinica:vacunas'),
            {'mascota': self.luna.pk, 'mes': '2026-10'},
        )

        self.assertEqual(
            self._dia(response, date(2026, 10, 20))['turnos'], [turno],
        )
        self.assertEqual(response.context['calendario']['turnos'], [turno])
        self.assertContains(response, 'ctubre de 2026')
        self.assertContains(response, 'data-fecha="2026-10-20"')
        self.assertContains(
            response, reverse('clinica:vacuna_turno', args=[turno.pk]),
        )
        self.assertContains(response, 'fa-syringe')
        self.assertContains(response, 'Triple felina')
        self.assertContains(response, '15:00')
        self.assertNotContains(response, 'Séxtuple')
        self.assertNotContains(response, 'No hay vacunas reservadas')

    def test_por_defecto_muestra_la_primera_mascota_y_el_mes_actual(self):
        response = self.client.get(reverse('clinica:vacunas'))

        self.assertEqual(
            response.context['calendario']['mascota'], self.firulais,
        )
        self.assertTrue(self._dia(response, date(2026, 10, 14))['es_hoy'])
        self.assertContains(response, 'No hay vacunas reservadas este mes')
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Luna')
        self.assertNotContains(response, 'Michi')

    def test_mascota_de_otro_dueno_en_la_url_da_404(self):
        for nombre in ('clinica:vacunas', 'clinica:vacuna_reservar'):
            with self.subTest(url=nombre):
                response = self.client.get(
                    reverse(nombre), {'mascota': self.michi.pk},
                )
                self.assertEqual(response.status_code, 404)

    def test_dueno_sin_mascotas_ve_el_estado_vacio(self):
        carla = crear_dueno('carla@mail.com', '31555666', 'Carla')
        self.client.force_login(carla.usuario)

        response = self.client.get(reverse('clinica:vacunas'))

        self.assertContains(response, 'Todavía no registraste mascotas')
        self.assertContains(response, reverse('clinica:mascota_nueva'))

    def test_detalle_muestra_el_turno_con_boton_cancelar(self):
        turno = self.crear_turno(
            self.luna, datetime(2026, 10, 20, 15, 0, tzinfo=ZONA),
            self.triple_felina,
        )

        response = self.client.get(
            reverse('clinica:vacuna_turno', args=[turno.pk]),
        )

        self.assertContains(response, 'Triple felina')
        self.assertContains(response, self.triple_felina.descripcion)
        self.assertContains(response, 'Luna')
        self.assertContains(response, 'Martes 20 de octubre de 2026')
        self.assertContains(response, '15:00 hs')
        self.assertContains(response, 'Dra. Paula Navarro')
        self.assertContains(response, 'Pendiente')
        self.assertContains(response, 'Sin pago registrado')
        self.assertContains(response, 'mes=2026-10')
        self.assertContains(
            response, reverse('atencion:turno_cancelar', args=[turno.pk]),
        )

    def test_cancelar_desde_el_detalle_vuelve_al_calendario(self):
        horario = horarios_libres_vacunacion()[-1]
        turno = reservar_turno_vacuna(
            self.ana, self.luna.pk, self.triple_felina.pk,
            horario['veterinario_id'], horario['fecha_hora'],
        )
        detalle = self.client.get(
            reverse('clinica:vacuna_turno', args=[turno.pk]),
        )
        link = html.unescape(re.search(
            r'href="([^"]*/cancelar/[^"]*)"', detalle.content.decode(),
        ).group(1))

        confirmacion = self.client.get(link)
        response = self.client.post(
            reverse('atencion:turno_cancelar', args=[turno.pk]),
            {'siguiente': confirmacion.context['siguiente']},
            follow=True,
        )

        self.assertContains(confirmacion, 'Triple felina')
        self.assertRedirects(
            response,
            f"{reverse('clinica:vacunas')}?mascota={self.luna.pk}"
            '&mes=2026-10',
        )
        self.assertContains(response, 'Se canceló el turno de Luna.')
        self.assertEqual(response.context['calendario']['turnos'], [])
        turno.refresh_from_db()
        self.assertEqual(turno.estado, 'CANCELADO')

    def test_detalle_de_turno_de_otro_dueno_da_404(self):
        turno = self.crear_turno(
            self.michi, AHORA + timedelta(days=1), self.triple_felina,
        )

        response = self.client.get(
            reverse('clinica:vacuna_turno', args=[turno.pk]),
        )

        self.assertEqual(response.status_code, 404)

    def test_paso_1_ofrece_solo_las_vacunas_de_su_especie(self):
        response = self.client.get(
            reverse('clinica:vacuna_reservar'), {'mascota': self.luna.pk},
        )

        self.assertContains(response, 'Triple felina')
        self.assertContains(response, 'Leucemia felina')
        self.assertNotContains(response, 'Séxtuple')
        self.assertNotContains(response, 'Tos de las perreras')

    def test_vacuna_de_otra_especie_en_la_url_vuelve_al_paso_1_con_error(
        self,
    ):
        response = self.client.get(
            reverse('clinica:vacuna_reservar'),
            {'mascota': self.luna.pk, 'vacuna': self.sextuple.pk},
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('clinica:vacuna_reservar')}?mascota={self.luna.pk}",
        )
        self.assertContains(response, 'es solo para perros')

    def test_paso_2_muestra_los_proximos_horarios_libres(self):
        response = self.client.get(
            reverse('clinica:vacuna_reservar'),
            {'mascota': self.luna.pk, 'vacuna': self.triple_felina.pk},
        )

        self.assertEqual(len(response.context['horarios']), 10)
        self.assertContains(response, '13:00 hs')
        self.assertContains(response, 'Dra. Paula Navarro')
        self.assertNotContains(response, 'Dr. Martín Sosa')

    def test_el_link_de_un_horario_lleva_a_la_confirmacion(self):
        paso_2 = self.client.get(
            reverse('clinica:vacuna_reservar'),
            {'mascota': self.luna.pk, 'vacuna': self.triple_felina.pk},
        )
        link = re.search(
            r'href="([^"]*fecha_hora=[^"]*)"', paso_2.content.decode(),
        ).group(1)

        response = self.client.get(html.unescape(link))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paso'], 3)
        self.assertEqual(
            response.context['horario']['fecha_hora'], AHORA.replace(hour=13),
        )
        self.assertContains(response, 'Confirmar turno')

    def test_reserva_completa_vuelve_al_calendario_con_la_etiqueta(self):
        horario = horarios_libres_vacunacion()[0]
        datos = {
            'mascota': self.luna.pk,
            'vacuna': self.triple_felina.pk,
            'veterinario': horario['veterinario_id'],
            'fecha_hora': horario['fecha_hora'].isoformat(),
        }

        confirmacion = self.client.get(
            reverse('clinica:vacuna_reservar'), datos,
        )
        response = self.client.post(
            reverse('clinica:vacuna_reservar'), datos, follow=True,
        )

        self.assertContains(confirmacion, 'Confirmar turno')
        turno = Turno.objects.get()
        self.assertEqual(turno.vacuna, self.triple_felina)
        self.assertRedirects(
            response,
            f"{reverse('clinica:vacunas')}?mascota={self.luna.pk}"
            '&mes=2026-10',
        )
        self.assertContains(
            response, '¡Turno de Triple felina reservado para Luna!',
        )
        self.assertEqual(
            self._dia(response, date(2026, 10, 14))['turnos'], [turno],
        )

    def test_post_con_horario_ya_ocupado_vuelve_al_paso_2_con_error(self):
        horario = horarios_libres_vacunacion()[0]
        self.crear_turno(
            self.firulais, horario['fecha_hora'], self.sextuple,
        )

        response = self.client.post(
            reverse('clinica:vacuna_reservar'),
            {
                'mascota': self.luna.pk,
                'vacuna': self.triple_felina.pk,
                'veterinario': horario['veterinario_id'],
                'fecha_hora': horario['fecha_hora'].isoformat(),
            },
            follow=True,
        )

        self.assertContains(response, 'acaba de ser reservado')
        self.assertEqual(Turno.objects.count(), 1)

    def test_navegacion_hacia_vacunas(self):
        inicio = self.client.get(reverse('core:inicio'))
        mascotas = self.client.get(reverse('clinica:mascotas'))

        self.assertContains(inicio, f'href="{reverse("clinica:vacunas")}"')
        self.assertContains(
            mascotas,
            f'{reverse("clinica:vacunas")}?mascota={self.luna.pk}',
        )
