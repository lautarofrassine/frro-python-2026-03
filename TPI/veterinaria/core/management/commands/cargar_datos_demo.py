import os

from django.core.management.base import BaseCommand, CommandError

from core.services.datos_demo import (
    DatosDemoError,
    borrar_datos_demo,
    cargar_datos_demo,
)


class Command(BaseCommand):
    help = (
        'Carga datos de demostracion (dueños @demo.clinicavet24.com con '
        'mascotas, turnos, pagos, historias y vacunas). La contraseña de '
        'los dueños sale de DEMO_PASSWORD. Con --borrar elimina solo los '
        'datos de demo.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--borrar',
            action='store_true',
            help='Elimina los dueños de demo y todo lo suyo.',
        )

    def handle(self, *args, **options):
        if options['borrar']:
            borrado = borrar_datos_demo()
            self.stdout.write(self.style.SUCCESS(
                'Datos de demo eliminados: '
                f"{borrado['duenos']} dueños, {borrado['mascotas']} "
                f"mascotas, {borrado['turnos']} turnos, {borrado['pagos']} "
                f"pagos y {borrado['historias']} entradas de historia "
                'clínica.'
            ))
            return

        try:
            resumen = cargar_datos_demo(os.getenv('DEMO_PASSWORD', ''))
        except DatosDemoError as error:
            raise CommandError(str(error))

        if resumen['ya_cargados']:
            self.stdout.write(self.style.WARNING(
                f"Los datos de demo ya estaban cargados ({resumen['duenos']} "
                'dueños): no se creó nada. Para volver a cargarlos, corré '
                'antes cargar_datos_demo --borrar.'
            ))
        else:
            self._resumen(resumen)
        self._acceso(resumen)

    def _resumen(self, r):
        escribir = self.stdout.write
        escribir(self.style.SUCCESS('Datos de demo cargados:'))
        escribir(f"  Dueños: {r['duenos']}")
        escribir(f"  Mascotas: {r['mascotas']}")
        escribir(
            f"  Turnos: {r['turnos_futuros']} futuros, "
            f"{r['turnos_pasados']} pasados y {r['turnos_cancelados']} "
            'cancelados'
        )
        escribir(
            f"  Turnos de {r['nombre_veterinario']}: "
            f"{r['turnos_veterinario_demo']}"
        )
        escribir('  Pagos: ' + ', '.join(
            f'{estado}: {cantidad}'
            for estado, cantidad in r['pagos'].items()
        ))
        escribir(f"  Entradas de historia clínica: {r['historias']}")
        escribir(f"  Vacunas aplicadas: {r['vacunas_aplicadas']}")

    def _acceso(self, r):
        escribir = self.stdout.write
        escribir('')
        escribir('Para la demo:')
        escribir(
            f"  Dueño: {r['email_principal']} "
            '(contraseña: la de DEMO_PASSWORD)'
        )
        if r['email_veterinario']:
            escribir(
                f"  Veterinaria: {r['email_veterinario']} "
                '(contraseña: la de VET_PASSWORD_INICIAL, o la que le '
                'hayan puesto)'
            )
        else:
            escribir(
                f"  Veterinaria: {r['nombre_veterinario']} no tiene cuenta; "
                'creala con python manage.py crear_usuarios_veterinarios.'
            )
