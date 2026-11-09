from django.contrib import admin

from .models import (
    HorarioAtencion,
    NivelUrgencia,
    PrecioVeterinario,
    Prescripcion,
    Turno,
    Veterinario,
)


class HorarioAtencionInline(admin.TabularInline):
    model = HorarioAtencion
    extra = 1


class PrecioVeterinarioInline(admin.TabularInline):
    """Solo lectura: los cambios los programa el veterinario en Mis
    precios, donde se validan las reglas."""
    model = PrecioVeterinario
    fields = ('monto', 'vigente_desde', 'creado')
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Veterinario)
class VeterinarioAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'matricula', 'especialidad', 'estado', 'usuario',
    )
    raw_id_fields = ('usuario',)
    filter_horizontal = ('obras_sociales',)
    search_fields = ('nombre', 'matricula', 'especialidad')
    list_filter = ('estado', 'especialidad')
    inlines = [HorarioAtencionInline, PrecioVeterinarioInline]


@admin.register(NivelUrgencia)
class NivelUrgenciaAdmin(admin.ModelAdmin):
    list_display = ('nivel_urgencia', 'sintomas_descripcion')
    list_filter = ('nivel_urgencia',)


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = (
        'mascota', 'veterinario', 'fecha_hora', 'tipo', 'nivel_urgencia',
        'estado',
    )
    list_filter = ('estado', 'tipo', 'veterinario')


@admin.register(Prescripcion)
class PrescripcionAdmin(admin.ModelAdmin):
    list_display = ('turno', 'medicamento', 'cantidad')
