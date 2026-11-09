from django.contrib import admin

from .models import Medicamento, ObraSocial, Pago


@admin.register(ObraSocial)
class ObraSocialAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'porcentaje_cobertura', 'tope_mensual', 'servicios',
        'activa',
    )
    list_filter = ('activa',)
    search_fields = ('nombre',)

    @admin.display(description='Servicios que cubre')
    def servicios(self, obra_social):
        return ', '.join(obra_social.servicios_cubiertos()) or '—'


@admin.register(Medicamento)
class MedicamentoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'stock_actual', 'stock_minimo', 'requiere_receta',
        'fecha_vencimiento',
    )
    search_fields = ('nombre',)
    list_filter = ('requiere_receta',)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = (
        'turno', 'monto_total', 'monto_cubierto_os', 'monto_a_pagar',
        'metodo', 'estado', 'numero_comprobante', 'fecha',
    )
    list_filter = ('metodo', 'estado')
    search_fields = ('numero_comprobante', 'mp_payment_id')
    readonly_fields = (
        'monto_total', 'monto_cubierto_os', 'monto_a_pagar',
        'detalle_cobertura', 'fecha', 'fecha_pago', 'numero_comprobante',
        'mp_preference_id', 'mp_payment_id',
    )
