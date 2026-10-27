import re
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
from django.urls import reverse

from atencion.models import NivelUrgencia, Turno
from atencion.services.turnos import reservar_turno
from atencion.tests.test_turnos import AHORA, MANANA_10, ZONA, TurnosBase
from clinica.models import HistorialClinico, Vacuna
from clinica.services.mascotas import registrar_mascota
from clinica.tests.test_mascotas import datos_mascota

PASSWORD = 'GuardiaSegura#2026'
URL_AGENDA = reverse('veterinario:agenda')


class VeterinarioBase(TurnosBase):
    """La Dra. Laura Fernandez (clinico) tiene cuenta. Ana (dueña de
    Firulais y Toby) y Beto (dueño de Michi) son dueños. Son las 12:00
    del miercoles 14/10/2026."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.usuario_vet = User.objects.create_user(
            username='laura.fernandez@clinicavet24.com',
            email='laura.fernandez@clinicavet24.com',
            first_name='Laura', password=PASSWORD,
        )
        cls.clinico.usuario = cls.usuario_vet
        cls.clinico.save()
        cls.usuario_cardio = User.objects.create_user(
            username='federico.acosta@clinicavet24.com',
        )
        cls.cardiologo.usuario = cls.usuario_cardio
        cls.cardiologo.save()
        cls.toby = registrar_mascota(cls.ana, **datos_mascota(nombre='Toby'))

    def setUp(self):
        super().setUp()
        parche = patch(
            'clinica.services.mascotas._hoy', return_value=AHORA.date(),
        )
        parche.start()
        self.addCleanup(parche.stop)

    def turno(self, mascota, veterinario, fecha_hora, **campos):
        dueno = mascota.dueno
        turno = reservar_turno(
            dueno, mascota.pk, veterinario.pk, fecha_hora,
            tipo=campos.pop('tipo', None), motivo=campos.pop('motivo', ''),
            nivel_urgencia=campos.pop('nivel', None),
        )
        for campo, valor in campos.items():
            setattr(turno, campo, valor)
        turno.save()
        return turno

    def como_veterinario(self):
        self.client.force_login(self.usuario_vet)


class LoginPorRolTests(VeterinarioBase):

    def _ingresar(self, usuario, password, siguiente=None):
        url = reverse('clinica:ingresar')
        if siguiente:
            url += f'?next={siguiente}'
        return self.client.post(
            url, {'username': usuario, 'password': password},
        )

    def test_el_veterinario_va_a_su_agenda(self):
        response = self._ingresar('Laura.Fernandez@clinicavet24.com', PASSWORD)

        self.assertRedirects(response, URL_AGENDA)
        self.assertEqual(
            int(self.client.session[SESSION_KEY]), self.usuario_vet.pk,
        )

    def test_el_dueno_va_a_su_panel(self):
        self.ana.usuario.set_password(PASSWORD)
        self.ana.usuario.save()

        response = self._ingresar('ana@mail.com', PASSWORD)

        self.assertRedirects(response, reverse('clinica:panel'))

    def test_next_se_respeta_solo_si_corresponde_al_rol(self):
        self.ana.usuario.set_password(PASSWORD)
        self.ana.usuario.save()
        historias = reverse('veterinario:historias')
        casos = (
            ('laura.fernandez@clinicavet24.com', historias, historias),
            ('laura.fernandez@clinicavet24.com', '/cuenta/mascotas/',
             URL_AGENDA),
            ('ana@mail.com', '/atencion/urgencia/', '/atencion/urgencia/'),
            ('ana@mail.com', URL_AGENDA, reverse('clinica:panel')),
        )
        for usuario, siguiente, destino in casos:
            with self.subTest(usuario=usuario, siguiente=siguiente):
                self.client.logout()
                response = self._ingresar(usuario, PASSWORD, siguiente)
                self.assertRedirects(
                    response, destino, fetch_redirect_response=False,
                )

    def test_el_panel_de_dueno_lleva_al_veterinario_a_su_agenda(self):
        self.como_veterinario()

        response = self.client.get(reverse('clinica:panel'))

        self.assertRedirects(response, URL_AGENDA)

    def test_la_registracion_sigue_creando_solo_duenos(self):
        response = self.client.post(reverse('clinica:registro'), {
            'nombre': 'Carla', 'apellido': 'Ruiz', 'dni': '31.555.666',
            'email': 'carla@mail.com', 'telefono': '341 555-1111',
            'password1': PASSWORD, 'password2': PASSWORD,
        })

        self.assertRedirects(response, reverse('clinica:panel'))
        usuario = get_user_model().objects.get(username='carla@mail.com')
        self.assertTrue(hasattr(usuario, 'dueno'))
        self.assertFalse(hasattr(usuario, 'veterinario'))

    def test_el_veterinario_no_puede_registrarse_como_dueno(self):
        self.como_veterinario()

        response = self.client.get(reverse('clinica:registro'), follow=True)

        self.assertRedirects(response, URL_AGENDA)


class PermisosPorRolTests(VeterinarioBase):

    def setUp(self):
        super().setUp()
        self.turno_firulais = self.turno(
            self.firulais, self.clinico, MANANA_10,
        )

    def _urls_de_veterinario(self):
        return [
            URL_AGENDA,
            reverse('veterinario:turno', args=[self.turno_firulais.pk]),
            reverse('veterinario:historias'),
            reverse('veterinario:historia', args=[self.firulais.pk]),
            reverse('veterinario:entrada_nueva', args=[self.firulais.pk]),
        ]

    def test_sin_sesion_redirige_a_ingresar(self):
        for url in self._urls_de_veterinario():
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('clinica:ingresar')}?next={url}",
                )

    def test_un_dueno_recibe_403(self):
        self.client.force_login(self.ana.usuario)

        for url in self._urls_de_veterinario():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertContains(
                    response, 'No tenés acceso a esta sección',
                    status_code=403,
                )

    def test_un_veterinario_no_entra_a_las_pantallas_de_dueno(self):
        self.como_veterinario()
        urls = [
            reverse('clinica:mascotas'),
            reverse('clinica:vacunas'),
            reverse('atencion:consultas'),
            reverse('atencion:turno_nuevo'),
            reverse('atencion:urgencia'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_el_menu_del_veterinario_tiene_sus_opciones(self):
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertContains(response, 'Hola, Dra. Laura Fernández')
        self.assertContains(response, 'Mi agenda')
        self.assertContains(response, 'Historias clínicas')
        self.assertContains(response, 'Salir')
        self.assertNotContains(response, 'Sacar turno')
        self.assertNotContains(response, 'Mis mascotas')
        self.assertNotContains(response, 'Mis consultas')

    def test_el_menu_del_dueno_no_cambia(self):
        self.client.force_login(self.ana.usuario)

        response = self.client.get(reverse('clinica:panel'))

        self.assertContains(response, 'Mis mascotas')
        self.assertContains(response, 'Sacar turno')
        self.assertNotContains(response, 'Mi agenda')


class AgendaTests(VeterinarioBase):

    def test_muestra_solo_los_turnos_del_veterinario_con_mascota_y_dueno(self):
        propio = self.turno(self.firulais, self.clinico, MANANA_10)
        self.turno(self.michi, self.cardiologo, MANANA_10.replace(hour=15))
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        dias = response.context['agenda']['dias']
        self.assertEqual(len(dias), 7)
        self.assertEqual(dias[0]['fecha'], datetime(2026, 10, 12).date())
        self.assertEqual(dias[3]['turnos'], [propio])
        self.assertEqual(
            sum(len(d['turnos']) for d in dias), 1,
        )
        self.assertContains(response, 'Firulais')
        self.assertContains(response, 'Ana Gómez')
        self.assertContains(response, '10:00')
        self.assertContains(response, 'fa-dog')
        self.assertNotContains(response, 'Michi')
        self.assertContains(
            response, reverse('veterinario:turno', args=[propio.pk]),
        )

    def test_no_muestra_turnos_cancelados(self):
        turno = self.turno(self.firulais, self.clinico, MANANA_10)
        turno.estado = Turno.Estado.CANCELADO
        turno.save()
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertNotContains(response, 'Firulais')

    def test_guardia_con_color_de_urgencia_y_vacuna_con_su_nombre(self):
        self.turno(
            self.firulais, self.clinico, AHORA.replace(hour=15),
            tipo='Guardia', nivel='CRITICA',
        )
        vacuna = Vacuna.objects.create(
            nombre='Séxtuple', nombre_corto='Séxtuple', especie='PERRO',
            descripcion='-', periodicidad_dias=365,
        )
        self.turno(
            self.toby, self.clinico, AHORA.replace(hour=16), vacuna=vacuna,
            tipo='Vacunación',
        )
        consulta = self.turno(self.michi, self.clinico, AHORA.replace(hour=17))
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertContains(response, 'text-bg-danger')
        self.assertContains(response, 'Crítica')
        self.assertContains(response, 'fa-syringe')
        self.assertContains(response, 'Séxtuple')
        self.assertEqual(consulta.nivel_urgencia.nivel_urgencia, 'BAJA')
        # La consulta comun tambien tiene nivel (BAJA), pero sin badge.
        self.assertNotContains(response, 'text-bg-success')

    def test_turnos_de_hoy_en_orden(self):
        tarde = self.turno(self.firulais, self.clinico, AHORA.replace(hour=17))
        temprano = self.turno(self.michi, self.clinico, AHORA.replace(hour=13))
        self.turno(self.toby, self.clinico, MANANA_10)
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertEqual(response.context['turnos_hoy'], [temprano, tarde])

    def test_cambia_de_semana_y_ofrece_volver_a_hoy(self):
        siguiente = self.turno(
            self.firulais, self.clinico, MANANA_10 + timedelta(weeks=1),
        )
        self.como_veterinario()

        actual = self.client.get(URL_AGENDA)
        otra = self.client.get(URL_AGENDA, {'semana': '2026-10-21'})

        self.assertContains(actual, 'semana=2026-10-19')
        self.assertContains(actual, 'semana=2026-10-05')
        self.assertNotContains(actual, '>Hoy</a>')
        self.assertEqual(otra.context['agenda']['dias'][3]['turnos'],
                         [siguiente])
        self.assertContains(otra, '>Hoy</a>')


class DetalleTurnoTests(VeterinarioBase):

    def test_muestra_mascota_dueno_turno_y_pago(self):
        turno = self.turno(
            self.firulais, self.clinico, AHORA.replace(hour=15),
            tipo='Guardia', nivel='ALTA', motivo='Vomita desde ayer',
        )
        self.como_veterinario()

        response = self.client.get(
            reverse('veterinario:turno', args=[turno.pk]),
        )

        for texto in ('Firulais', 'Perro', 'Mestizo', '6 años y 5 meses',
                      '12,50 kg', 'Ana Gómez', '341 555-0000',
                      'ana@mail.com', 'Guardia', 'Vomita desde ayer',
                      'Alta', 'bg-alta', 'Pendiente', '$15.000'):
            with self.subTest(texto=texto):
                self.assertContains(response, texto)
        self.assertContains(
            response, reverse('veterinario:historia', args=[self.firulais.pk]),
        )
        self.assertContains(
            response,
            reverse('veterinario:entrada_nueva', args=[self.firulais.pk])
            + f'?turno={turno.pk}',
        )

    def test_turno_de_otro_veterinario_da_404(self):
        ajeno = self.turno(
            self.michi, self.cardiologo, MANANA_10.replace(hour=15),
        )
        self.como_veterinario()

        response = self.client.get(
            reverse('veterinario:turno', args=[ajeno.pk]),
        )

        self.assertEqual(response.status_code, 404)


class HistoriasClinicasTests(VeterinarioBase):

    def setUp(self):
        super().setUp()
        self.turno_firulais = self.turno(
            self.firulais, self.clinico, MANANA_10,
        )
        self.turno_michi = self.turno(
            self.michi, self.clinico, MANANA_10.replace(hour=11),
        )
        # Toby solo fue atendido por el cardiologo.
        self.turno_toby = self.turno(
            self.toby, self.cardiologo, MANANA_10.replace(hour=15),
        )
        self.como_veterinario()

    def test_lista_solo_las_mascotas_atendidas_o_agendadas(self):
        response = self.client.get(reverse('veterinario:historias'))

        self.assertEqual(
            [m.nombre for m in response.context['mascotas']],
            ['Firulais', 'Michi'],
        )
        self.assertNotContains(response, 'Toby')

    def test_busca_por_nombre_de_mascota_o_de_dueno(self):
        por_mascota = self.client.get(
            reverse('veterinario:historias'), {'q': 'firu'},
        )
        por_dueno = self.client.get(
            reverse('veterinario:historias'), {'q': 'beto'},
        )
        sin_resultados = self.client.get(
            reverse('veterinario:historias'), {'q': 'toby'},
        )

        self.assertEqual(
            [m.nombre for m in por_mascota.context['mascotas']], ['Firulais'],
        )
        self.assertEqual(
            [m.nombre for m in por_dueno.context['mascotas']], ['Michi'],
        )
        self.assertContains(sin_resultados, 'No encontramos mascotas')

    def test_historia_de_una_mascota_no_atendida_da_404(self):
        for nombre in ('veterinario:historia', 'veterinario:entrada_nueva'):
            with self.subTest(url=nombre):
                response = self.client.get(
                    reverse(nombre, args=[self.toby.pk]),
                )
                self.assertEqual(response.status_code, 404)

    def test_la_historia_muestra_las_entradas_de_todos_los_veterinarios(self):
        vieja = HistorialClinico.objects.create(
            mascota=self.firulais, veterinario=self.cardiologo,
            diagnostico='Soplo leve', tratamiento='Control en 6 meses',
        )
        nueva = HistorialClinico.objects.create(
            mascota=self.firulais, veterinario=self.clinico,
            diagnostico='Gastritis', tratamiento='Dieta blanda',
            observaciones='Volver si sigue vomitando',
            turno=self.turno_firulais,
        )

        response = self.client.get(
            reverse('veterinario:historia', args=[self.firulais.pk]),
        )

        self.assertEqual(response.context['entradas'], [nueva, vieja])
        for texto in ('Soplo leve', 'Control en 6 meses',
                      'Dr. Federico Acosta',
                      'Gastritis', 'Dieta blanda', 'Volver si sigue vomitando',
                      'Dra. Laura Fernández', 'Ana Gómez', '341 555-0000'):
            with self.subTest(texto=texto):
                self.assertContains(response, texto)
        # Solo puede editar la propia.
        self.assertContains(
            response, reverse('veterinario:entrada_editar', args=[nueva.pk]),
        )
        self.assertNotContains(
            response, reverse('veterinario:entrada_editar', args=[vieja.pk]),
        )

    def test_cargar_entrada_desde_el_turno_la_guarda_con_veterinario_y_turno(
        self,
    ):
        url = reverse('veterinario:entrada_nueva', args=[self.firulais.pk])

        formulario = self.client.get(url, {'turno': self.turno_firulais.pk})
        response = self.client.post(url, {
            'turno': self.turno_firulais.pk,
            'diagnostico': 'Otitis externa',
            'tratamiento': 'Gotas óticas cada 12 hs',
            'observaciones': '',
        }, follow=True)

        self.assertContains(formulario, 'turno del 15/10/2026 10:00 hs')
        entrada = HistorialClinico.objects.get()
        self.assertEqual(entrada.mascota, self.firulais)
        self.assertEqual(entrada.veterinario, self.clinico)
        self.assertEqual(entrada.turno, self.turno_firulais)
        self.assertEqual(entrada.diagnostico, 'Otitis externa')
        self.assertRedirects(
            response, reverse('veterinario:historia', args=[self.firulais.pk]),
        )
        self.assertContains(
            response, 'Entrada guardada en la historia clínica de Firulais.',
        )

    def test_entrada_sin_turno_y_datos_incompletos(self):
        url = reverse('veterinario:entrada_nueva', args=[self.firulais.pk])

        incompleta = self.client.post(url, {
            'diagnostico': '', 'tratamiento': 'Algo',
        })
        self.client.post(url, {
            'diagnostico': 'Control', 'tratamiento': 'Nada',
        })

        self.assertIn('diagnostico', incompleta.context['form'].errors)
        entrada = HistorialClinico.objects.get()
        self.assertIsNone(entrada.turno)
        self.assertEqual(entrada.veterinario, self.clinico)

    def test_no_se_puede_asociar_la_entrada_a_un_turno_ajeno(self):
        url = reverse('veterinario:entrada_nueva', args=[self.firulais.pk])

        for turno in (self.turno_michi, self.turno_toby):
            with self.subTest(turno=turno.pk):
                response = self.client.post(url, {
                    'turno': turno.pk, 'diagnostico': 'X', 'tratamiento': 'Y',
                })
                self.assertEqual(response.status_code, 404)
        self.assertEqual(HistorialClinico.objects.count(), 0)

    def test_edita_solo_sus_propias_entradas(self):
        propia = HistorialClinico.objects.create(
            mascota=self.michi, veterinario=self.clinico,
            diagnostico='Conjuntivitis', tratamiento='Colirio',
        )
        ajena = HistorialClinico.objects.create(
            mascota=self.michi, veterinario=self.cardiologo,
            diagnostico='Soplo', tratamiento='Control',
        )
        de_mascota_no_atendida = HistorialClinico.objects.create(
            mascota=self.toby, veterinario=self.cardiologo,
            diagnostico='Arritmia', tratamiento='Holter',
        )

        editada = self.client.post(
            reverse('veterinario:entrada_editar', args=[propia.pk]),
            {'diagnostico': 'Conjuntivitis bacteriana',
             'tratamiento': 'Colirio antibiótico',
             'observaciones': 'Ojo der.'},
        )
        respuesta_ajena = self.client.post(
            reverse('veterinario:entrada_editar', args=[ajena.pk]),
            {'diagnostico': 'Cambiado', 'tratamiento': 'Cambiado'},
        )
        respuesta_no_atendida = self.client.get(
            reverse('veterinario:entrada_editar',
                    args=[de_mascota_no_atendida.pk]),
        )

        self.assertRedirects(
            editada, reverse('veterinario:historia', args=[self.michi.pk]),
        )
        propia.refresh_from_db()
        self.assertEqual(propia.diagnostico, 'Conjuntivitis bacteriana')
        self.assertEqual(respuesta_ajena.status_code, 403)
        ajena.refresh_from_db()
        self.assertEqual(ajena.diagnostico, 'Soplo')
        self.assertEqual(respuesta_no_atendida.status_code, 404)

    def test_el_nivel_de_urgencia_de_consulta_no_aparece_como_guardia(self):
        # Todo turno tiene un nivel (BAJA por defecto) aunque no sea de
        # guardia: no se muestra en el detalle.
        self.assertTrue(NivelUrgencia.objects.filter(nivel_urgencia='BAJA'))

        response = self.client.get(
            reverse('veterinario:turno', args=[self.turno_firulais.pk]),
        )

        self.assertNotContains(response, 'Nivel de urgencia')


class AgendaSinTurnosTests(VeterinarioBase):

    def test_un_veterinario_sin_turnos_ve_la_agenda_vacia(self):
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertContains(response, 'No tenés turnos hoy.')
        self.assertContains(response, 'Sin turnos', count=7)

    def test_un_veterinario_nuevo_tiene_la_semana_del_domingo(self):
        domingo = datetime(2026, 10, 18, 0, 0, tzinfo=ZONA)
        self.como_veterinario()

        response = self.client.get(URL_AGENDA)

        self.assertEqual(
            response.context['agenda']['dias'][6]['fecha'], domingo.date(),
        )


class NavegacionVeterinarioTests(VeterinarioBase):

    LINKS_LANDING = ('#servicios', '#como-funciona', '#contacto')

    def _links_del_menu(self, contenido):
        """(href, activo) de cada link del menu central."""
        menu = re.search(
            r'<ul class="navbar-nav mx-auto[^"]*">(.*?)</ul>', contenido,
            re.S,
        ).group(1)
        return [
            (href, 'active' in clase)
            for clase, href in re.findall(
                r'<a class="(nav-link[^"]*)"[^>]*\s+href="([^"]+)"', menu,
            )
        ]

    def test_la_navbar_del_veterinario_tiene_solo_agenda_e_historias(self):
        self.como_veterinario()

        contenido = self.client.get(URL_AGENDA).content.decode()

        self.assertEqual(
            [href for href, _ in self._links_del_menu(contenido)],
            [URL_AGENDA, reverse('veterinario:historias')],
        )
        for ancla in self.LINKS_LANDING:
            with self.subTest(ancla=ancla):
                self.assertNotIn(ancla, contenido)
        self.assertIn('Salir', contenido)

    def test_marca_la_pagina_activa(self):
        turno = self.turno(self.firulais, self.clinico, MANANA_10)
        self.como_veterinario()
        historias = reverse('veterinario:historias')
        casos = (
            (URL_AGENDA, URL_AGENDA),
            (reverse('veterinario:turno', args=[turno.pk]), URL_AGENDA),
            (historias, historias),
            (reverse('veterinario:historia', args=[self.firulais.pk]),
             historias),
            (reverse('veterinario:entrada_nueva', args=[self.firulais.pk]),
             historias),
        )
        for url, activo in casos:
            with self.subTest(url=url):
                contenido = self.client.get(url).content.decode()
                activos = [
                    href for href, es_activo in self._links_del_menu(contenido)
                    if es_activo
                ]
                self.assertEqual(activos, [activo])
                self.assertIn('aria-current="page"', contenido)

    def test_el_logo_lleva_a_la_agenda(self):
        self.como_veterinario()

        response = self.client.get(reverse('veterinario:historias'))

        self.assertRegex(
            response.content.decode(),
            r'class="navbar-brand[^"]*"\s+href="/veterinario/agenda/"',
        )

    def test_un_veterinario_que_entra_al_inicio_va_a_su_agenda(self):
        self.como_veterinario()

        response = self.client.get(reverse('core:inicio'))

        self.assertRedirects(response, URL_AGENDA)

    def test_dueno_y_visitante_siguen_viendo_la_landing(self):
        for usuario in (None, self.ana.usuario):
            with self.subTest(usuario=usuario):
                self.client.logout()
                if usuario:
                    self.client.force_login(usuario)

                response = self.client.get(reverse('core:inicio'))
                contenido = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'core/inicio.html')
                self.assertEqual(
                    [href for href, _ in self._links_del_menu(contenido)],
                    ['/', '/#servicios', '/#como-funciona', '/#contacto'],
                )
                self.assertRegex(
                    contenido, r'class="navbar-brand[^"]*"\s+href="/"',
                )
                self.assertNotIn(f'href="{URL_AGENDA}"', contenido)
