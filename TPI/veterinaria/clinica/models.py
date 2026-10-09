from django.conf import settings
from django.db import models


class Dueno(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dueno',
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    dni = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True)
    telefono = models.CharField(max_length=20)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    obra_social = models.ForeignKey(
        'administracion.ObraSocial',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='duenos',
    )

    class Meta:
        verbose_name = 'Dueño'
        verbose_name_plural = 'Dueños'

    def __str__(self):
        return f'{self.nombre} {self.apellido} ({self.dni})'


class Mascota(models.Model):
    nombre = models.CharField(max_length=100)
    especie = models.CharField(max_length=50)
    raza = models.CharField(max_length=50)
    fecha_nacimiento = models.DateField()
    peso_kg = models.DecimalField(max_digits=5, decimal_places=2)
    dueno = models.ForeignKey(
        Dueno,
        on_delete=models.CASCADE,
        related_name='mascotas',
    )
    vacunas = models.ManyToManyField(
        'Vacuna',
        through='AplicacionVacuna',
        related_name='mascotas',
    )

    class Meta:
        verbose_name = 'Mascota'
        verbose_name_plural = 'Mascotas'

    def __str__(self):
        return f'{self.nombre} ({self.especie})'


class Vacuna(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()
    periodicidad_dias = models.IntegerField()

    class Meta:
        verbose_name = 'Vacuna'
        verbose_name_plural = 'Vacunas'

    def __str__(self):
        return self.nombre


class AplicacionVacuna(models.Model):
    mascota = models.ForeignKey(
        Mascota,
        on_delete=models.CASCADE,
        related_name='aplicaciones_vacuna',
    )
    vacuna = models.ForeignKey(
        Vacuna,
        on_delete=models.PROTECT,
        related_name='aplicaciones',
    )
    fecha_aplicacion = models.DateField()

    class Meta:
        verbose_name = 'Aplicación de vacuna'
        verbose_name_plural = 'Aplicaciones de vacuna'

    def __str__(self):
        return f'{self.vacuna} a {self.mascota} el {self.fecha_aplicacion}'


class HistorialClinico(models.Model):
    mascota = models.ForeignKey(
        Mascota,
        on_delete=models.CASCADE,
        related_name='historial_clinico',
    )
    fecha = models.DateTimeField(auto_now_add=True)
    diagnostico = models.TextField()
    tratamiento = models.TextField()
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Entrada de historial clínico'
        verbose_name_plural = 'Historial clínico'

    def __str__(self):
        return f'Historial de {self.mascota} - {self.fecha:%Y-%m-%d}'
