# Escrita a mano por el mismo motivo que la 0002: makemigrations exige
# un default para agregar el veterinario (obligatorio) a una tabla
# existente. Se agrega nullable y despues se pasa a NOT NULL; con la
# tabla vacia (estado actual en Aiven) funciona, y si hubiera filas el
# AlterField falla en lugar de inventarles un veterinario.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinica', '0004_vacuna_especie_nombre_corto'),
        ('atencion', '0007_veterinario_usuario'),
    ]

    operations = [
        migrations.AddField(
            model_name='historialclinico',
            name='veterinario',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='entradas_historia',
                to='atencion.veterinario',
            ),
        ),
        migrations.AlterField(
            model_name='historialclinico',
            name='veterinario',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='entradas_historia',
                to='atencion.veterinario',
            ),
        ),
        migrations.AddField(
            model_name='historialclinico',
            name='turno',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='entradas_historia',
                to='atencion.turno',
            ),
        ),
    ]
