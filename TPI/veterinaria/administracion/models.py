from django.db import models


class ObraSocial(models.Model):
    nombre = models.CharField(max_length=100)
    porcentaje_cobertura = models.DecimalField(max_digits=5, decimal_places=2)
    servicio_cubierto = models.CharField(max_length=200)
    tope_mensual = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Obra social'
        verbose_name_plural = 'Obras sociales'

    def __str__(self):
        return self.nombre


class Medicamento(models.Model):
    nombre = models.CharField(max_length=100)
    stock_actual = models.IntegerField()
    stock_minimo = models.IntegerField()
    requiere_receta = models.BooleanField(default=False)
    fecha_vencimiento = models.DateField()

    class Meta:
        verbose_name = 'Medicamento'
        verbose_name_plural = 'Medicamentos'

    def __str__(self):
        return self.nombre


class Pago(models.Model):
    class Metodo(models.TextChoices):
        EFECTIVO = 'EFECTIVO', 'Efectivo'
        TARJETA = 'TARJETA', 'Tarjeta'
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferencia'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        PAGADO = 'PAGADO', 'Pagado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    turno = models.ForeignKey(
        'atencion.Turno',
        on_delete=models.CASCADE,
        related_name='pagos',
    )
    monto_total = models.DecimalField(max_digits=10, decimal_places=2)
    monto_cubierto_os = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
    )
    # Vacio mientras el pago esta pendiente: todavia no se eligio.
    metodo = models.CharField(
        max_length=20, choices=Metodo.choices, blank=True,
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'

    def __str__(self):
        return f'Pago #{self.pk} - Turno {self.turno_id} ({self.estado})'
