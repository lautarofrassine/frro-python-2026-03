from django.db import models


class Veterinario(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = 'ACTIVO', 'Activo'
        INACTIVO = 'INACTIVO', 'Inactivo'

    nombre = models.CharField(max_length=100)
    matricula = models.CharField(max_length=20, unique=True)
    especialidad = models.CharField(max_length=100)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.ACTIVO,
    )

    class Meta:
        verbose_name = 'Veterinario'
        verbose_name_plural = 'Veterinarios'

    def __str__(self):
        return f'{self.nombre} (mat. {self.matricula})'

class HorarioAtencion(models.Model):
    class DiaSemana(models.IntegerChoices):
        LUNES = 0, 'Lunes'
        MARTES = 1, 'Martes'
        MIERCOLES = 2, 'Miércoles'
        JUEVES = 3, 'Jueves'
        VIERNES = 4, 'Viernes'
        SABADO = 5, 'Sábado'
        DOMINGO = 6, 'Domingo'

    veterinario = models.ForeignKey(Veterinario, on_delete=models.CASCADE, related_name='horarios_atencion')
    dia_semana = models.IntegerField(choices=DiaSemana.choices)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    class Meta:
        verbose_name = 'Horario de Atención'
        unique_together = ('veterinario', 'dia_semana', 'hora_inicio')

class NivelUrgencia(models.Model):
    class Nivel(models.TextChoices):
        BAJA = 'BAJA', 'Baja'
        MEDIA = 'MEDIA', 'Media'
        ALTA = 'ALTA', 'Alta'
        CRITICA = 'CRITICA', 'Crítica'

    sintomas_descripcion = models.TextField()
    nivel_urgencia = models.CharField(max_length=10, choices=Nivel.choices)

    class Meta:
        verbose_name = 'Nivel de urgencia'
        verbose_name_plural = 'Niveles de urgencia'

    def __str__(self):
        return f'{self.get_nivel_urgencia_display()}'


class Turno(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        EN_CURSO = 'EN_CURSO', 'En curso'
        FINALIZADO = 'FINALIZADO', 'Finalizado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    mascota = models.ForeignKey(
        'clinica.Mascota',
        on_delete=models.CASCADE,
        related_name='turnos',
    )
    veterinario = models.ForeignKey(
        Veterinario,
        on_delete=models.PROTECT,
        related_name='turnos',
    )
    nivel_urgencia = models.ForeignKey(
        NivelUrgencia,
        on_delete=models.PROTECT,
        related_name='turnos',
    )
    fecha_hora = models.DateTimeField()
    tipo = models.CharField(max_length=50)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    medicamentos = models.ManyToManyField(
        'administracion.Medicamento',
        through='Prescripcion',
        related_name='turnos',
    )

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'

    def __str__(self):
        return f'Turno {self.mascota} - {self.fecha_hora:%Y-%m-%d %H:%M}'


class Prescripcion(models.Model):
    turno = models.ForeignKey(
        Turno,
        on_delete=models.CASCADE,
        related_name='prescripciones',
    )
    medicamento = models.ForeignKey(
        'administracion.Medicamento',
        on_delete=models.PROTECT,
        related_name='prescripciones',
    )
    cantidad = models.IntegerField()

    class Meta:
        verbose_name = 'Prescripción'
        verbose_name_plural = 'Prescripciones'

    def __str__(self):
        return f'{self.cantidad} x {self.medicamento} (turno {self.turno_id})'
