from django.core.management.base import BaseCommand

from administracion.services.obras_sociales import (
    asignar_obras_sociales_de_prueba,
    cargar_obras_sociales_iniciales,
)


class Command(BaseCommand):
    help = (
        'Carga las obras sociales iniciales (ficticias). Se puede correr '
        'varias veces: no duplica y actualiza los datos de las que ya '
        'existen.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--asignar-veterinarios',
            action='store_true',
            help=(
                'Ademas, a cada veterinario activo que no atiende ninguna '
                'obra social le asigna entre 1 y 3 (datos de prueba).'
            ),
        )

    def handle(self, *args, **options):
        resumen = cargar_obras_sociales_iniciales()
        self.stdout.write(self.style.SUCCESS(
            f"Obras sociales: {resumen['creadas']} creadas, "
            f"{resumen['existentes']} ya existían (datos actualizados)."
        ))
        if options['asignar_veterinarios']:
            cambiados = asignar_obras_sociales_de_prueba()
            self.stdout.write(self.style.SUCCESS(
                f'Veterinarios con obras sociales asignadas: {cambiados}.'
            ))
