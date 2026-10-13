# Escrita a mano por el mismo motivo que la 0002 y la 0003:
# makemigrations exige un default para agregar campos NOT NULL a una
# tabla existente. Se agregan nullable y despues se pasan a NOT NULL;
# con la tabla de vacunas vacia (estado actual en Aiven) funciona, y si
# hubiera filas el AlterField falla en lugar de cargar datos ficticios.

from django.db import migrations, models

ESPECIES = [('PERRO', 'Perro'), ('GATO', 'Gato')]


class Migration(migrations.Migration):

    dependencies = [
        ('clinica', '0003_mascota_especie_activo_fecha_alta'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacuna',
            name='especie',
            field=models.CharField(
                choices=ESPECIES, max_length=10, null=True,
            ),
        ),
        migrations.AddField(
            model_name='vacuna',
            name='nombre_corto',
            field=models.CharField(max_length=15, null=True),
        ),
        migrations.AlterField(
            model_name='vacuna',
            name='especie',
            field=models.CharField(choices=ESPECIES, max_length=10),
        ),
        migrations.AlterField(
            model_name='vacuna',
            name='nombre_corto',
            field=models.CharField(max_length=15),
        ),
    ]
