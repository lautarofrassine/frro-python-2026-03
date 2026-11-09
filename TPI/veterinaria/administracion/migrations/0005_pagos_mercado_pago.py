"""Modulo de pagos (RF07): monto a pagar, estados CUBIERTO_OS y
REEMBOLSADO, metodos MERCADO_PAGO y EFECTIVO, comprobante y datos de
Mercado Pago.

monto_a_pagar se agrega primero sin valor por defecto (null), se completa
con monto_total - monto_cubierto_os para los pagos existentes (sin tocar
sus estados) y recien despues pasa a obligatorio."""
from django.db import migrations, models
from django.db.models import F


def completar_monto_a_pagar(apps, schema_editor):
    Pago = apps.get_model('administracion', 'Pago')
    Pago.objects.filter(monto_a_pagar__isnull=True).update(
        monto_a_pagar=F('monto_total') - F('monto_cubierto_os'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('administracion', '0004_obra_social_servicios_activa'),
    ]

    operations = [
        migrations.AddField(
            model_name='pago',
            name='monto_a_pagar',
            field=models.DecimalField(
                decimal_places=2, max_digits=10, null=True,
            ),
        ),
        migrations.AddField(
            model_name='pago',
            name='detalle_cobertura',
            field=models.CharField(blank=True, default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pago',
            name='fecha_pago',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pago',
            name='numero_comprobante',
            field=models.CharField(
                blank=True, max_length=20, null=True, unique=True,
            ),
        ),
        migrations.AddField(
            model_name='pago',
            name='mp_preference_id',
            field=models.CharField(blank=True, default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pago',
            name='mp_payment_id',
            field=models.CharField(blank=True, default='', max_length=50),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='pago',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('PAGADO', 'Pagado'),
                    ('CUBIERTO_OS', 'Cubierto por la obra social'),
                    ('CANCELADO', 'Cancelado'),
                    ('REEMBOLSADO', 'Reembolsado'),
                ],
                default='PENDIENTE',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='pago',
            name='metodo',
            field=models.CharField(
                blank=True,
                choices=[
                    ('MERCADO_PAGO', 'Mercado Pago'),
                    ('EFECTIVO', 'Efectivo'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(
            completar_monto_a_pagar, migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='pago',
            name='monto_a_pagar',
            field=models.DecimalField(decimal_places=2, max_digits=10),
        ),
    ]
