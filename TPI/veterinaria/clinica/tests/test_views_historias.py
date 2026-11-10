"""Historia clinica para el dueño: solo lectura y solo de sus mascotas."""
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from atencion.tests.test_turnos import crear_veterinario
from clinica.models import HistorialClinico
from clinica.services.historias import historia_de_mascota_para_dueno
from clinica.services.mascotas import (
    MascotaNoEncontrada,
    dar_de_baja_mascota,
    registrar_mascota,
)
from clinica.tests.test_mascotas import crear_dueno, datos_mascota

ZONA = ZoneInfo('America/Argentina/Buenos_Aires')
HOY = datetime(2026, 10, 14, 12, 0, tzinfo=ZONA).date()
URL_HISTORIAS = reverse('clinica:historias')


def url_historia(mascota):
    return reverse('clinica:historia', args=[mascota.pk])


class HistoriasDuenoBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.clinico = crear_veterinario(
            'Dra. Laura Fernández', 'MP-5001', 'CLINICA_GENERAL',
            time(8, 0), time(19, 0),
        )
        cls.dermatologo = crear_veterinario(
            'Dr. Pablo Ruiz', 'MP-5003', 'DERMATOLOGIA',
            time(8, 0), time(19, 0),
        )
        cls.ana = crear_dueno()
        cls.firulais = registrar_mascota(cls.ana, **datos_mascota())
        cls.beto = crear_dueno('beto@mail.com', '29333444', 'Beto')
        cls.michi = registrar_mascota(
            cls.beto, **datos_mascota(nombre='Michi', especie='GATO'),
        )

    def setUp(self):
        parche = patch('clinica.services.mascotas._hoy', return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)
        self.client.force_login(self.ana.usuario)

    def entrada(self, mascota, veterinario, fecha, diagnostico, **campos):
        entrada = HistorialClinico.objects.create(
            mascota=mascota, veterinario=veterinario,
            diagnostico=diagnostico,
            tratamiento=campos.get('tratamiento', 'Reposo'),
            observaciones=campos.get('observaciones', ''),
        )
        # fecha es auto_now_add: se ajusta despues de crearla.
        HistorialClinico.objects.filter(pk=entrada.pk).update(fecha=fecha)
        return entrada


class ListadoTests(HistoriasDuenoBase):

    def test_con_una_mascota_va_directo_a_su_historia(self):
        response = self.client.get(URL_HISTORIAS)

        self.assertRedirects(response, url_historia(self.firulais))

    def test_con_varias_muestra_la_seleccion(self):
        luna = registrar_mascota(
            self.ana, **datos_mascota(nombre='Luna', especie='GATO'),
        )

        response = self.client.get(URL_HISTORIAS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['mascotas']), [self.firulais, luna],
        )
        self.assertContains(response, url_historia(self.firulais))
        self.assertContains(response, url_historia(luna))
        self.assertContains(response, 'fa-dog')
        self.assertContains(response, 'fa-cat')
        self.assertNotContains(response, 'Michi')
        # Desde la historia se puede volver a elegir.
        self.assertContains(
            self.client.get(url_historia(luna)), 'Elegir otra mascota',
        )

    def test_las_mascotas_dadas_de_baja_no_cuentan(self):
        luna = registrar_mascota(
            self.ana, **datos_mascota(nombre='Luna', especie='GATO'),
        )
        dar_de_baja_mascota(self.ana, luna.pk)

        response = self.client.get(URL_HISTORIAS)

        self.assertRedirects(response, url_historia(self.firulais))

    def test_sin_mascotas_ofrece_registrar_una(self):
        dar_de_baja_mascota(self.ana, self.firulais.pk)

        response = self.client.get(URL_HISTORIAS)

        self.assertContains(response, 'Todavía no registraste mascotas')
        self.assertContains(response, reverse('clinica:mascota_nueva'))

    def test_sin_sesion_redirige_a_ingresar(self):
        self.client.logout()
        ingresar = reverse('clinica:ingresar')
        for url in (URL_HISTORIAS, url_historia(self.firulais)):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url), f'{ingresar}?next={url}',
                    fetch_redirect_response=False,
                )

    def test_un_veterinario_no_entra(self):
        usuario = get_user_model().objects.create_user(username='laura')
        self.clinico.usuario = usuario
        self.clinico.save()
        self.client.force_login(usuario)

        self.assertEqual(self.client.get(URL_HISTORIAS).status_code, 403)

    def test_la_tarjeta_del_inicio_y_el_menu_llevan_a_la_historia(self):
        self.assertContains(
            self.client.get(reverse('clinica:panel')),
            f'href="{URL_HISTORIAS}"',
        )
        self.client.logout()

        response = self.client.get(reverse('core:inicio'))

        self.assertRegex(
            response.content.decode(),
            rf'href="{URL_HISTORIAS}"\s+id="tarjeta-historia"\s+'
            r'class="stretched-link',
        )


class HistoriaTests(HistoriasDuenoBase):

    def test_muestra_las_entradas_de_la_mas_reciente_a_la_mas_vieja(self):
        vieja = self.entrada(
            self.firulais, self.clinico,
            datetime(2026, 3, 2, 10, 30, tzinfo=ZONA), 'Control anual',
        )
        nueva = self.entrada(
            self.firulais, self.dermatologo,
            datetime(2026, 9, 20, 16, 0, tzinfo=ZONA), 'Dermatitis',
            tratamiento='Shampoo medicado',
            observaciones='Volver en 15 días',
        )
        self.entrada(
            self.michi, self.clinico,
            datetime(2026, 9, 21, 9, 0, tzinfo=ZONA), 'Otitis de Michi',
        )

        response = self.client.get(url_historia(self.firulais))

        self.assertEqual(list(response.context['entradas']), [nueva, vieja])
        contenido = response.content.decode()
        self.assertLess(contenido.index('20/09/2026 16:00'),
                        contenido.index('02/03/2026 10:30'))
        for texto in ('Dr. Pablo Ruiz', 'Dra. Laura Fernández',
                      'Dermatitis', 'Shampoo medicado', 'Volver en 15 días',
                      'Control anual'):
            self.assertIn(texto, contenido)
        self.assertNotIn('Otitis de Michi', contenido)
        self.assertIn('class="linea-tiempo"', contenido)

    def test_sin_entradas_muestra_el_mensaje(self):
        response = self.client.get(url_historia(self.firulais))

        self.assertContains(
            response,
            'Todavía no hay atenciones registradas para Firulais',
        )

    def test_mascota_ajena_o_inexistente_da_404(self):
        for mascota_id in (self.michi.pk, 9999):
            with self.subTest(mascota_id=mascota_id):
                response = self.client.get(
                    reverse('clinica:historia', args=[mascota_id]),
                )
                self.assertEqual(response.status_code, 404)
        with self.assertRaises(MascotaNoEncontrada):
            historia_de_mascota_para_dueno(self.ana, self.michi.pk)

    def test_es_solo_lectura(self):
        self.entrada(
            self.firulais, self.clinico,
            datetime(2026, 9, 20, 16, 0, tzinfo=ZONA), 'Control',
        )

        response = self.client.get(url_historia(self.firulais))
        contenido = response.content.decode()

        # Solo el formulario de "Salir" de la navbar.
        self.assertEqual(contenido.count('<form'), 1)
        self.assertNotIn('Nueva entrada', contenido)
        self.assertNotIn('Editar', contenido)
        self.assertNotIn('/veterinario/', contenido)
        # POST no crea nada.
        self.client.post(url_historia(self.firulais), {
            'diagnostico': 'X', 'tratamiento': 'Y',
        })
        self.assertEqual(HistorialClinico.objects.count(), 1)
