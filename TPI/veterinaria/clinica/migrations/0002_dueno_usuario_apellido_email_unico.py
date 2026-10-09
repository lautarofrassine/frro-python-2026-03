# Escrita a mano: makemigrations exige un default para agregar campos
# NOT NULL a una tabla existente. En vez de inventar uno, cada campo se
# agrega como nullable y despues se pasa a NOT NULL. Con la tabla vacia
# (estado actual en Aiven) funciona; si hubiera filas, el AlterField
# falla en lugar de cargar datos ficticios.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinica', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='dueno',
            name='apellido',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='dueno',
            name='usuario',
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='dueno',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='dueno',
            name='apellido',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='dueno',
            name='usuario',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='dueno',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='dueno',
            name='email',
            field=models.EmailField(max_length=254, unique=True),
        ),
    ]
