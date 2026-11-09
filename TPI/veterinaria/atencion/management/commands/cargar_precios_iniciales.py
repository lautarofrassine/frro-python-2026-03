from django.core.management.base import BaseCommand

from atencion.services.precios import (
    VIGENCIA_PRECIO_INICIAL,
    cargar_precios_iniciales,
)


class Command(BaseCommand):
    help = (
        'A cada veterinario sin precio le crea uno con el de su '
        'especialidad, vigente desde el '
        f'{VIGENCIA_PRECIO_INICIAL:%d/%m/%Y}. Se puede correr varias '
        'veces: no duplica.'
    )

    def handle(self, *args, **options):
        creados = cargar_precios_iniciales()
        self.stdout.write(self.style.SUCCESS(
            f'Precios iniciales creados: {creados}.'
        ))
