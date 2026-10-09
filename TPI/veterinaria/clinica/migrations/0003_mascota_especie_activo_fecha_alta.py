# Escrita a mano por el mismo motivo que la 0002: makemigrations exige
# un default para agregar fecha_alta (auto_now_add) a una tabla
# existente. Se agrega nullable y despues se pasa a NOT NULL; con la
# tabla vacia (estado actual en Aiven) funciona. Django pone un DEFAULT
# temporal en la columna durante el ALTER pero no ejecuta UPDATE sobre
# filas existentes, asi que si hubiera filas con NULL el MODIFY ... NOT
# NULL fallaria (modo estricto de MySQL) en lugar de inventarles fecha.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinica', '0002_dueno_usuario_apellido_email_unico'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mascota',
            name='especie',
            field=models.CharField(
                choices=[('PERRO', 'Perro'), ('GATO', 'Gato')],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='mascota',
            name='activo',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='mascota',
            name='fecha_alta',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='mascota',
            name='fecha_alta',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
