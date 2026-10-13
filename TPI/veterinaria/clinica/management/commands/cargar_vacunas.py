from django.core.management.base import BaseCommand

from clinica.services.vacunas import cargar_vacunas_iniciales


class Command(BaseCommand):
    help = (
        'Carga las vacunas iniciales de perros y gatos. Se puede correr '
        'varias veces: no duplica.'
    )

    def handle(self, *args, **options):
        resumen = cargar_vacunas_iniciales()
        self.stdout.write(self.style.SUCCESS(
            f"Vacunas: {resumen['creadas']} creadas, "
            f"{resumen['existentes']} ya existían."
        ))
