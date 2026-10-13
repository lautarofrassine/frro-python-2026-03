from django.core.management.base import BaseCommand

from atencion.services.veterinarios import cargar_veterinarios_iniciales


class Command(BaseCommand):
    help = (
        'Carga los veterinarios ficticios iniciales (3 por especialidad) '
        'con su horario de atencion. Se puede correr varias veces: no '
        'duplica.'
    )

    def handle(self, *args, **options):
        resumen = cargar_veterinarios_iniciales()

        total_creados = total_existentes = 0
        for especialidad, cantidades in resumen.items():
            total_creados += cantidades['creados']
            total_existentes += cantidades['existentes']
            self.stdout.write(
                f"{especialidad}: {cantidades['creados']} creados, "
                f"{cantidades['existentes']} ya existían"
            )
        self.stdout.write(self.style.SUCCESS(
            f'Total: {total_creados} creados, {total_existentes} ya '
            'existían.'
        ))
