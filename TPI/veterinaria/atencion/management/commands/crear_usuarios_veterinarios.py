import os

from django.core.management.base import BaseCommand, CommandError

from atencion.services.veterinarios import (
    CuentaVeterinarioError,
    crear_usuarios_veterinarios,
    veterinarios_con_cuenta,
)


class Command(BaseCommand):
    help = (
        'Crea la cuenta (email + contraseña inicial) de cada veterinario '
        'activo que todavia no tiene. La contraseña inicial se lee de la '
        'variable de entorno VET_PASSWORD_INICIAL. Se puede correr varias '
        'veces: no toca a los que ya tienen cuenta.'
    )

    def handle(self, *args, **options):
        try:
            creados = crear_usuarios_veterinarios(
                os.getenv('VET_PASSWORD_INICIAL', ''),
            )
        except CuentaVeterinarioError as error:
            raise CommandError(str(error))

        nuevos = {veterinario.pk for veterinario in creados}
        cuentas = veterinarios_con_cuenta()
        ancho_nombre = max([len('Veterinario')] + [
            len(v.nombre) for v in cuentas
        ])
        ancho_especialidad = max([len('Especialidad')] + [
            len(v.get_especialidad_display()) for v in cuentas
        ])

        self.stdout.write(
            f"{'Veterinario':<{ancho_nombre}}  "
            f"{'Especialidad':<{ancho_especialidad}}  Email"
        )
        self.stdout.write('-' * (ancho_nombre + ancho_especialidad + 40))
        for veterinario in cuentas:
            marca = '  (nueva)' if veterinario.pk in nuevos else ''
            especialidad = veterinario.get_especialidad_display()
            self.stdout.write(
                f'{veterinario.nombre:<{ancho_nombre}}  '
                f'{especialidad:<{ancho_especialidad}}  '
                f'{veterinario.usuario.email}{marca}'
            )
        self.stdout.write(self.style.SUCCESS(
            f'Cuentas creadas: {len(creados)}. Ya existían: '
            f'{len(cuentas) - len(creados)}.'
        ))
