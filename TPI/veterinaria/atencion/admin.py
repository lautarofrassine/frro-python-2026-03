from django.contrib import admin

from .models import NivelUrgencia, Prescripcion, Turno, Veterinario,HorarioAtencion

class HorarioAtencionInline(admin.TabularInline):
    model=HorarioAtencion
    extra=1

@admin.register(Veterinario)
class VeterinarioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'matricula', 'especialidad', 'estado')
    search_fields = ('nombre', 'matricula', 'especialidad')
    list_filter = ('estado', 'especialidad')
    inlines=[HorarioAtencionInline]


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