"""A cada veterinario sin precio le crea uno con el precio de su
especialidad, vigente desde el 01/01/2026. Los valores son una copia de
PRECIO_POR_ESPECIALIDAD (atencion/services/precios.py) al momento de esta
migracion: las migraciones no importan codigo de la aplicacion."""
from datetime import date
from decimal import Decimal

from django.db import migrations

VIGENTE_DESDE = date(2026, 1, 1)
PRECIO_POR_ESPECIALIDAD = {
    'CLINICA_GENERAL': Decimal('15000'),
    'CARDIOLOGIA': Decimal('28000'),
    'DERMATOLOGIA': Decimal('22000'),
    'TRAUMATOLOGIA': Decimal('25000'),
    'GASTROENTEROLOGIA': Decimal('24000'),
    'OFTALMOLOGIA': Decimal('23000'),
    'VACUNACION': Decimal('12000'),
    'GUARDIA': Decimal('30000'),
}
PRECIO_BASE = PRECIO_POR_ESPECIALIDAD['CLINICA_GENERAL']


def crear_precios_iniciales(apps, schema_editor):
    Veterinario = apps.get_model('atencion', 'Veterinario')
    PrecioVeterinario = apps.get_model('atencion', 'PrecioVeterinario')
    PrecioVeterinario.objects.bulk_create([
        PrecioVeterinario(
            veterinario=veterinario,
            monto=PRECIO_POR_ESPECIALIDAD.get(
                veterinario.especialidad, PRECIO_BASE,
            ),
            vigente_desde=VIGENTE_DESDE,
        )
        for veterinario in Veterinario.objects.filter(precios__isnull=True)
    ])


def borrar_precios_iniciales(apps, schema_editor):
    PrecioVeterinario = apps.get_model('atencion', 'PrecioVeterinario')
    PrecioVeterinario.objects.filter(vigente_desde=VIGENTE_DESDE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('atencion', '0009_precio_veterinario'),
    ]

    operations = [
        migrations.RunPython(
            crear_precios_iniciales, borrar_precios_iniciales,
        ),
    ]
